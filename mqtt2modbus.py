#!/usr/bin/env python3

import logging
from queue import PriorityQueue
import threading
import time
import json
import sys
import os
import signal
import click
import systemd.daemon as sysd

from pymodbus.client import ModbusSerialClient as ModbusClient
from pymodbus.exceptions import ModbusIOException

import paho.mqtt.client as mqtt_client
from paho.mqtt.enums import CallbackAPIVersion
from utils import ModbusFunc, ModbusMsg, ModbusMsgBlock, ModuleStatus, ThermometerData, SHT30Data, load_config

def _log_uncaught(atype, value, tb):
	logger.error(f"Uncaught exception: {str(atype)} : {value}", exc_info=(atype, value, tb))
	os.kill(os.getpid(), signal.SIGKILL)


def _handle_uncaught(type, value, tb):
	_log_uncaught(type, value, tb)

def _handle_uncaught_th(args):
	_log_uncaught(args.exc_type, args.exc_value, args.exc_traceback)

# Setup exception handling
# add sys.excepthook to handle exceptions raised in the main thread
sys.excepthook = _handle_uncaught
# add threading excepthook to handle exceptions raised in threads started as Thread.run
threading.excepthook = _handle_uncaught_th

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("mqtt2modbus")

def on_connect(client, userdara, flags, rc, properties):
	logger.info(f"Connected to MQTT with result {rc}")
	client.subscribe('modbus/#')

def on_message(client, userdata, msg):
	top = msg.topic.split("/")[1:]
	
	if top[0] == "led":
		led_message(top[1:],userdata,msg)

def led_message(topic, userdata, msg):
	unit = int(topic[0])
	#print(f"{unit=}")
	if topic[1] == 'set':
		msg = ModbusMsg(unit=unit, func=ModbusFunc.SET_HOLDING, reg = 0, val =int(msg.payload),priority=5)
		if topic[2] == 'pwm0':
			msg.reg = 10
			mqtt_queue.put(msg)
		elif topic[2] == 'pwm1':
			msg.reg = 11
			mqtt_queue.put(msg)
		elif topic[2] == 'pwm2':
			msg.reg = 12
			mqtt_queue.put(msg)
	if topic[1] == 'get':
		pass

def send_modbus_message(msg:ModbusMsg):
	logger.info(f"Sending meesage {msg}")
	start = time.time()
	if isinstance(msg, ModbusMsg):
		if msg.func == ModbusFunc.SET_HOLDING:
			rq = client.write_registers(msg.reg, [msg.val], device_id=msg.unit)

	if isinstance(msg, ModbusMsgBlock):
		resps = []
		for m in msg.msgs:
			if m.func == ModbusFunc.READ_HOLDING:
				rq = client.read_holding_registers(m.reg, count=m.nregs, device_id=m.unit)
				if type(rq) == ModbusIOException:
					logger.warning(f"Unit {m.unit} got ModbusIOException: {rq}")
					return 
				resps.append(rq.registers)
			if m.func == ModbusFunc.READ_INPUT:
				rq = client.read_input_registers(m.reg, count=m.nregs, device_id=m.unit)
				if type(rq) == ModbusIOException:
					logger.warning(f"Unit {m.unit} ModbusIOException: {rq}")
					return
				resps.append(rq.registers)

			if m.func == ModbusFunc.SET_HOLDING:
				rq = client.write_registers(m.reg, [m.val], device_id=m.unit)
				if type(rq) == ModbusIOException:
					logger.warning(f"Unit {m.unit} ModbusIOException: {rq}")
					return
				resps.append(rq.registers)
		logger.info(f"Unit: {m.unit}, responses: {resps}")
		msg.callback(m.unit,resps)
	logger.info(f"Took {time.time()-start:.2} seconds")

def publish_status_regs(unit,resp):
	status = ModuleStatus.from_regs(resp)
	msg = {"id": "modbus", "type": "status", "unit": unit, "timestamp": time.time()} | status.to_dict()
	mqtt.publish("modbus/status", json.dumps(msg))
	logger.debug((unit,status))

def publish_thermometer(unit,resps):
	for resp in resps:
		data = ThermometerData.from_regs(resp,therm_names)
		if data is None:
			# Empty or stale slot (exception 02 -> empty register list).
			continue
		msg = {"id": "modbus", "type": "thermometer", "unit": unit, "timestamp": time.time()} | data.to_dict()
		mqtt.publish("modbus/thermometer", json.dumps(msg))
		logger.debug((unit,data))



def publish_sht30(unit,resps):
	data = SHT30Data.from_regs(resps[0])
	if data is None:
		# Firmware answers exception 02 when the reading is stale (sensor unplugged or I2C fault).
		if unit not in sht30_stale:
			logger.warning(f"Unit {unit}: SHT30 reading not available (stale or missing)")
			sht30_stale.add(unit)
		return
	if unit in sht30_stale:
		logger.info(f"Unit {unit}: SHT30 reading available again")
		sht30_stale.discard(unit)
	msg = {"id": "modbus", "type": "sht30", "unit": unit, "timestamp": time.time()} | data.to_dict()
	mqtt.publish("modbus/sht30", json.dumps(msg))
	logger.debug((unit,data))


def read_status_regs():
	for unit in UNITS:
		msgs = []
		msgs.append(ModbusMsg(unit=unit, func=ModbusFunc.READ_INPUT, reg = 5, nregs=4))
		msgs.append(ModbusMsg(unit=unit, func=ModbusFunc.READ_HOLDING, reg = 1, nregs=2))
		mqtt_queue.put(ModbusMsgBlock(msgs=msgs, callback=publish_status_regs))
		# One 5-register read per thermometer slot (200 + 5*n). Each slot is
		# read separately because the firmware answers exception 02 for an
		# empty/stale slot and a multi-register read would fail as a whole.
		msgs = [ModbusMsg(unit=unit, func=ModbusFunc.READ_INPUT, reg = 200 + 5*n, nregs=5)
				for n in range(N_THERMOMETERS)]
		mqtt_queue.put(ModbusMsgBlock(msgs=msgs, callback=publish_thermometer))
		if unit in SHT30_UNITS:
			msgs = [ModbusMsg(unit=unit, func=ModbusFunc.READ_INPUT, reg = 40, nregs=2)]
			mqtt_queue.put(ModbusMsgBlock(msgs=msgs, callback=publish_sht30))
	threading.Timer(1,read_status_regs).start()

@click.command()
@click.option('--config', default="default", type=str, help="Config file to use")
@click.option('--config_dir', type=str, default=None, help="Base directory for config files")
def main(config, config_dir):
	global UNITS
	global N_THERMOMETERS
	global SHT30_UNITS
	global sht30_stale
	global mqtt
	global mqtt_queue
	global client
	global therm_names


	logger.info("Starting up...")

	cfg = load_config(config,subpath="mqtt2modbus",config_dir=config_dir)
	UNITS = cfg["units"]
	# Thermometer slots to poll per unit (5 input registers each from 200).
	# Old 1-Wire firmware and the LED boards expose 2, the 8-sensor firmware 8.
	N_THERMOMETERS = int(cfg.get("n_thermometers", 2))
	# Units carrying an SHT30 (input registers 40/41); optional, defaults to none.
	SHT30_UNITS = cfg.get("sht30_units", []) or []
	sht30_stale = set()


	therm_names = load_config("therm_names",config_dir=config_dir)

	mqtt_queue = PriorityQueue()

	mqtt = mqtt_client.Client(CallbackAPIVersion.VERSION2)
	mqtt.on_connect = on_connect
	mqtt.on_message = on_message

	mqtt.connect("localhost", 1883, keepalive=60)

	mqtt.loop_start()

	client = ModbusClient(
				port=cfg["port"]["path"], 
				timeout=cfg["port"].get("timeout",0.1),
				baudrate=cfg["port"].get("baudrate",115200))
	client.connect()

	threading.Timer(1,read_status_regs).start()

	sysd.notify("READY=1")


	while True:
		msg = mqtt_queue.get()
		logger.info(f"In queue: {mqtt_queue.qsize()}")
		
		send_modbus_message(msg)

		mqtt_queue.task_done()

if __name__ == "__main__":
	main(standalone_mode=False)
