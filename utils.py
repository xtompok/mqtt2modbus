from dataclasses import dataclass
from enum import Enum, auto
from typing import Callable

class ModbusFunc(Enum):
    READ_HOLDING = auto()
    READ_INPUT = auto()
    SET_HOLDING = auto()


@dataclass
class ModbusMsg(object):
    func: ModbusFunc
    unit: int
    reg: int
    val: int = None
    nregs: int = 0

@dataclass
class ModbusMsgBlock(object):
    msgs: list
    callback: Callable[[int,list],None]

@dataclass
class ModuleStatus(object):
    status: int
    uptime: int
    vin: float
    iin: float
    v3v3: int
    int_temp: float

    @classmethod
    def from_regs(cls,regs):
        return cls(vin = regs[0][0] / 1000, iin = regs[0][1], v3v3 = regs[0][2], int_temp = regs[0][3], status = regs[1][0], uptime = regs[1][1])

    def __str__(self):
        return f"Status: {self.status}, uptime[~s]: {self.uptime}, V_in[V]: {self.vin}, I_in[mA]: {self.iin}, 3V3[mV]: {self.v3v3}, internal temp[deg C]: {self.int_temp}"

    def to_dict(self):
        return {"status": self.status, "uptime": self.uptime, "vin": self.vin, "iin": self.iin, "v3v3": self.v3v3, "int_temp": self.int_temp}



