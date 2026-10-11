# mqtt2modbus
Convert MQTT messages to ModBus for light control, and poll Modbus boards
(status, DS18B20 thermometers, SHT30) into MQTT.

Per-instance config lives in `~/config/mqtt2modbus/<name>.yaml`:

```yaml
port:
  path: /dev/serial/by-id/...
  timeout: 0.1
  baudrate: 115200
units: [101]        # unit IDs to poll
sht30_units: [101]  # optional: units carrying an SHT30 (input registers 40/41)
```

Published topics: `modbus/status`, `modbus/thermometer`, `modbus/sht30`
(`temperature` in deg C, `humidity` in %RH).
