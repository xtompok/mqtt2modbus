#!/bin/sh

cp mqtt2modbus@.service /home/automation/.config/systemd/user/

systemctl --user daemon-reload

systemctl --user enable mqtt2modbus@lights.service
systemctl --user restart mqtt2modbus@lights.service
systemctl --user status mqtt2modbus@lights.service

systemctl --user enable mqtt2modbus@1wire.service
systemctl --user restart mqtt2modbus@1wire.service
systemctl --user status mqtt2modbus@1wire.service
