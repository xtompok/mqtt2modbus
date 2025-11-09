#!/usr/bin/env python3

import logging
from queue import Queue
import threading
import time
import json
import sys
import os
import signal
import systemd.daemon as sysd

from pymodbus.client import ModbusSerialClient as ModbusClient
from pymodbus.exceptions import ModbusIOException

import paho.mqtt.client as mqtt_client
from utils import ModbusFunc, ModbusMsg, ModbusMsgBlock, ModuleStatus

MODBUS_PORT='/dev/serial_lights'

UNITS=[2,4,5,6,7,8,9]

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

logger.info("Starting up...")

mqtt_queue = Queue()

def on_connect(client, userdara, flags, rc):
	logger.info(f"Connected to MQTT with result {rc}")
	mqtt.subscribe('modbus/#')

def on_message(client, userdata, msg):
	top = msg.topic.split("/")[1:]
	
	if top[0] == "led":
		led_message(top[1:],userdata,msg)

def led_message(topic, userdata, msg):
	unit = int(topic[0])
	#print(f"{unit=}")
	if topic[1] == 'set':
		msg = ModbusMsg(unit=unit, func=ModbusFunc.SET_HOLDING, reg = 0, val =int(msg.payload))
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
	if isinstance(msg, ModbusMsg):
		if msg.func == ModbusFunc.SET_HOLDING:
			rq = client.write_registers(msg.reg, [msg.val], slave=msg.unit)

	if isinstance(msg, ModbusMsgBlock):
		resps = []
		for m in msg.msgs:
			if m.func == ModbusFunc.READ_HOLDING:
				rq = client.read_holding_registers(m.reg, m.nregs, slave=m.unit)
				if type(rq) == ModbusIOException:
					logger.warning(f"Unit {m.unit} got ModbusIOException: {rq}")
					return 
				resps.append(rq.registers)
			if m.func == ModbusFunc.READ_INPUT:
				rq = client.read_input_registers(m.reg, m.nregs, slave=m.unit)
				if type(rq) == ModbusIOException:
					logger.warning(f"Unit {m.unit} ModbusIOException: {rq}")
					return
				resps.append(rq.registers)

			if m.func == ModbusFunc.SET_HOLDING:
				rq = client.write_registers(m.reg, [m.val], slave=m.unit)
				if type(rq) == ModbusIOException:
					logger.warning(f"Unit {m.unit} ModbusIOException: {rq}")
					return
				resps.append(rq.registers)
		msg.callback(m.unit,resps)

def publish_status_regs(unit,resp):
	status = ModuleStatus.from_regs(resp)
	msg = {"id": "modbus", "type": "status", "unit": unit, "timestamp": time.time()} | status.to_dict()
	mqtt.publish("modbus/status", json.dumps(msg))
	logger.debug(unit,status) 

def read_status_regs():
	for unit in UNITS:
		msgs = []
		msgs.append(ModbusMsg(unit=unit, func=ModbusFunc.READ_INPUT, reg = 5, nregs=4))
		msgs.append(ModbusMsg(unit=unit, func=ModbusFunc.READ_HOLDING, reg = 1, nregs=2))
		mqtt_queue.put(ModbusMsgBlock(msgs=msgs, callback=publish_status_regs))
	threading.Timer(1,read_status_regs).start()


mqtt = mqtt_client.Client()
mqtt.on_connect = on_connect
mqtt.on_message = on_message

mqtt.connect("localhost", 1883, keepalive=60)

mqtt.loop_start()

client = ModbusClient(
			port=MODBUS_PORT, 
			timeout=1,
			baudrate=115200)
client.connect()

threading.Timer(1,read_status_regs).start()

sysd.notify("READY=1")


while True:
	msg = mqtt_queue.get()
	
	send_modbus_message(msg)

	mqtt_queue.task_done()
