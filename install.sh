#!/bin/sh

cp mqtt2modbus.service /home/automation/.config/systemd/user/

systemctl --user daemon-reload

systemctl --user enable mqtt2modbus.service
systemctl --user restart mqtt2modbus.service
systemctl --user status mqtt2modbus.service
