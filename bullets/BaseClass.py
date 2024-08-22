from typing import Dict, Union

"""
该目录下用于放置额外处理脚本，扫描时仅扫描该目录下的脚本
"""
class _BaseRequestClass(object):
    """
    该类用于为发送封禁请求提供模板
    扫描模块时只会扫描该类的子类

    ID: 类的唯一标识符，无需自己定义
    self.name: 发送模块在前端显示的名称

    self.request(self, ip, data): 发送请求所用的函数，参数ip为选定的ip，返回一个字典，标准字典结构为
    {
        "status": 0或者1,1代表请求成功，0代表失败,
        "message": 在前端展示的信息,
        "error": 如果发送失败，在前端展示的信息,
        "data": 需要往前端发送的数据（目前未应用）
    }
    """
    ID: int = ...
    def __init__(self):
        self.name: str = ...


    def request(self, ip: str, data: dict) -> Dict[Union[str, int], Union[str, int, dict, list]]:
        """
        发送封禁请求所用的函数，创建子类时请覆盖该函数

        :param ip: 所需封禁的ip
        :param data: 前端传过来的数据，在 <输入数据> 处设置，字典格式，编写脚本时可进行利用，例如获取请求对应网站所需的Cookie
        :return: 封禁的情况
        """
        return {"status": 0, "message": "", "error": "", "data": {}}