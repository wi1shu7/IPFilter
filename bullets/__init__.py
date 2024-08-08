import os
import importlib
import inspect

from bullets.BaseClass import _BaseRequestClass


class SingletonMeta(type):
    _instances = {}

    def __call__(cls, *args, **kwargs):
        if cls not in cls._instances:
            instance = super(SingletonMeta, cls).__call__(*args, **kwargs)
            cls._instances[cls] = instance
        return cls._instances[cls]


class _Bullets(metaclass=SingletonMeta):
    subclasses = {}

    def __init__(self):
        self.discover_subclasses()

    def discover_subclasses(self):
        for filename in os.listdir(os.path.dirname(os.path.abspath(__file__))):
            # 过滤出 Python 文件
            if filename.endswith('.py') and filename != os.path.basename(__file__):
                module_name = filename[:-3]

                module = importlib.import_module("bullets." + module_name)
                i = 1
                # 获取模块中的所有类
                for name, obj in inspect.getmembers(module, inspect.isclass):
                    if issubclass(obj, _BaseRequestClass) and obj != _BaseRequestClass:
                        obj.ID = i
                        i += 1
                        self.subclasses.update({obj.ID: obj()})

    def get_subclasses_name(self):
        request_modules = {}
        for _id, ins in self.subclasses.items():
            request_modules.update({_id: ins.name})
        return request_modules


Bullets = _Bullets()

__all__ = [
    "Bullets",
    "_BaseRequestClass",
    "SingletonMeta"
]
