import base64
import ipaddress
import json
import os
import chardet

import asyncio
import sys

import httpx
from quart import Quart, render_template, Blueprint, request, abort, jsonify, make_response, url_for

from bullets import Bullets, SingletonMeta

class _utils(metaclass=SingletonMeta):
    def __init__(self):
        self.ipaddress_white_list = []
        self.ipaddress_black_list = []
        self.load_ips()

        self.config: dict = ...
        self.load_config()

        self.client = httpx.AsyncClient(verify=False)

    def __del__(self):
        asyncio.run(self.client.aclose())

    def __calculate_ips(self, cidr):
        network = ipaddress.ip_network(cidr, strict=False)
        ip_list = [str(ip) for ip in network.hosts()]
        return ip_list

    @staticmethod
    def is_valid_ip(ip_str):
        try:
            ipaddress.ip_address(ip_str)
            return True
        except ValueError:
            return False

    @staticmethod
    def get_return_templates(status, message="", error="", data=None):
        if data is None:
            data = {}
        return {"status": status, "message": message, "error": error, "data": data}

    def load_ips(self):
        self.ipaddress_white_list = []
        self.ipaddress_black_list = []
        for path in ['white', 'black']:
            ipaddress_set = set()
            list_path = os.path.join("data", path)
            for filename in os.listdir(list_path):
                file_path = os.path.join(list_path, filename)

                if os.path.isfile(file_path):
                    with open(file_path, 'rb') as file:
                        raw_data = file.read()
                        result = chardet.detect(raw_data)
                        encoding = result['encoding']

                    with open(file_path, 'r', encoding=encoding) as file:
                        for line in file:
                            ipaddress_one_list = self.__calculate_ips(line.strip())
                            for ip in ipaddress_one_list:
                                ipaddress_set.add(ip)

            setattr(self, f"ipaddress_{path}_list", list(ipaddress_set))

    def load_config(self):
        with open(os.path.join('data', 'config.json'), 'r', encoding='utf-8') as f:
            self.config = json.load(f)

    def save_config(self):
        with open(os.path.join('data', 'config.json'), 'w', encoding='utf-8') as f:
            json.dump(self.config, f, ensure_ascii=False, indent=4)

    @staticmethod
    def chunk_list(data, chunk_size=20):
        """将列表分成每组指定大小的子列表"""
        for i in range(0, len(data), chunk_size):
            yield data[i:i + chunk_size]


    async def search_qax_ip(self, param, apikey):
        url = "https://webapi.ti.qianxin.com/ip/v3/reputation"

        headers = {
            "Content-type": "application/json",
            'Api-Key': apikey
        }

        payload = {
            "param": param
        }

        response = await self.client.get(url, params=payload, headers=headers)
        if response.status_code == 200:
            data = response.json()
            return data
        else:
            return {'status': 0}

    async def filter_ip_list(self, ip_list, qax_ti_key=None, weibu_ti_key=None):
        result = {ip: {
            "whiteIp": ip in self.ipaddress_white_list,
            "blackIp": ip in self.ipaddress_black_list,
            "ipData": {},
            "qaxTi": {},
            "weibuTi": {}
        } for ip in ip_list}

        if qax_ti_key:
            tasks = []
            for ip, ip_info in result.items():
                if not ip_info['whiteIp'] or ip_info['blackIp']:
                    tasks.append(self.search_qax_ip(ip, qax_ti_key))
            qax_ti_results = []

            for i in range(0, len(tasks), self.config['batch_size']):
                batch_tasks = tasks[i:i + self.config['batch_size']]
                qax_ti_results.extend(await asyncio.gather(*batch_tasks))
                await asyncio.sleep(self.config['request_delay'])

            for qax_ti_one_result in qax_ti_results:
                if qax_ti_one_result['status'] == 10000:
                    for ip, _ in qax_ti_one_result['data'].items():
                        result[ip]['qaxTi'] = qax_ti_one_result

        return result

    def background_lock(self):
        if self.config['bk_lock']:
            self.config['bk_lock'] = False
            self.save_config()
            return 1
        else:
            self.config['bk_lock'] = True
            self.save_config()
            return 0
class _app:
    def __init__(self):
        self.app = Quart(__name__)
        self.utils = _utils()

        self.api_bp = Blueprint('api', __name__)

        self.__blueprint_register()
        self.app.register_blueprint(self.api_bp, url_prefix='/api')

        @self.app.template_filter('show_invisible')
        def show_invisible(value):
            invisible_chars = {
                ' ': '<空格>',
                '\t': '<制表符>',
                '\n': '<换行符>',
                '\r': '<回车符>',
                '\x0b': '<垂直制表符>',
                '\x0c': '<换页符>'
            }
            return ''.join(invisible_chars.get(char, char) for char in value)

        @self.app.route('/')
        async def home():
            ti_key_base64 = request.cookies.get('ti_key', '{}')
            ti_key = base64.b64decode(ti_key_base64.encode('utf-8')).decode('utf-8')
            try:
                api_keys = json.loads(ti_key) if ti_key else {
                    'qax': '',
                    'weibu': ''
                }
            except json.JSONDecodeError:
                api_keys = {
                    'qax': '',
                    'weibu': ''
                }
            try:
                qax_ti_key = api_keys.get('qax', '')
                weibu_api_key = api_keys.get('weibu', '')
            except AttributeError:
                qax_ti_key = weibu_api_key = ''

            carry_data_b64 = request.cookies.get('carry_data', "")
            carry_data = base64.b64decode(carry_data_b64.encode('utf-8')).decode('utf-8') if carry_data_b64 else ""

            bk_lock = self.utils.config['bk_lock']
            bk_url = url_for('static', filename='bk3.jpg') if bk_lock else self.utils.config['bk_url']

            return await render_template("index.html",
                                         qax_ti_key=qax_ti_key,
                                         weibu_api_key=weibu_api_key,
                                         carry_data=carry_data,
                                         bk_url=bk_url,
                                         bk_lock=bk_lock,
                                         config=self.utils.config,
                                         bullets=Bullets.get_subclasses_name()
                                         )

    def __blueprint_register(self):

        @self.api_bp.route("/process_ips", methods=['POST'])
        async def api_process_ips():
            api_keys = request.headers.get('x-api-keys', '{}')
            api_keys = json.loads(api_keys)

            qax_ti_key = api_keys.get('qax', None)
            weibu_ti_key = api_keys.get('weibu', None)

            data = await request.get_json()
            bs4_ips = data.get("data", None)

            decollator = data.get("decollator", None)
            if decollator:
                if not decollator == self.utils.config['decollator']:
                    self.utils.config['decollator'] = decollator
                    self.utils.save_config()
            else:
                decollator = self.utils.config['decollator']

            if bs4_ips:
                ip_input = base64.b64decode(bs4_ips).decode('utf-8')
                ip_lines = [ip.strip() for ip in ip_input.split('\n') if ip.strip()]
                ips_set = set()
                for ip_line in ip_lines:
                    for ip in ip_line.split(decollator):
                        if self.utils.is_valid_ip(ip):
                            ips_set.add(ip.strip())
                        else:
                            return jsonify(self.utils.get_return_templates(0, error="输入的ip有误"))

                ips = list(ips_set)

                ips_filter_result = await self.utils.filter_ip_list(ips, qax_ti_key=qax_ti_key, weibu_ti_key=weibu_ti_key)

                response = await make_response(self.utils.get_return_templates(1, data=ips_filter_result))

                response.set_cookie('ti_key', base64.b64encode(json.dumps(api_keys).encode('utf-8')).decode('utf-8'), httponly=True)

                return response

            return abort(400)

        @self.api_bp.route("/refresh_ips", methods=['POST'])
        async def api_refresh_ips():
            self.utils.load_ips()
            return jsonify(self.utils.get_return_templates(1, message="刷新成功"))

        @self.api_bp.route("/bk_lock", methods=['GET'])
        async def api_bk_lock():
            bk_status = self.utils.background_lock()
            return jsonify(self.utils.get_return_templates(1, message="更改成功", data={"status": bk_status}))

        @self.api_bp.route('/speed_change', methods=["POST"])
        async def api_speed_change():
            speed_data = await request.json
            speed_config = {key: speed_data[key] if key in speed_data else self.utils.config[key] for key in self.utils.config}
            self.utils.config.update(speed_config)
            self.utils.save_config()
            return jsonify(self.utils.get_return_templates(1, "更改成功"))

        @self.api_bp.route('/request', methods=["POST"])
        async def api_request():
            bullet_info = await request.json

            try:
                response_bullet = Bullets.subclasses[
                    bullet_info['id']
                ].request(bullet_info['ip'], bullet_info['data'])
            except Exception:
                exc_type, exc_value, exc_tb = sys.exc_info()
                return jsonify(self.utils.get_return_templates(0, error=f"请求错误：{exc_type.__name__}: {exc_value}"))

            response = await make_response(jsonify(
                response_bullet
            ))
            if bullet_info['data']:
                response.set_cookie("carry_data",
                                    base64.b64encode(
                                        json.dumps(bullet_info['data']).encode('utf-8')
                                    ).decode('utf-8'), httponly=True)
            else:
                response.set_cookie("carry_data", "", expires=0)
            return response

        @self.api_bp.errorhandler(400)
        async def bad_request_400(e):
            return self.utils.get_return_templates(0, error=f"400：{e}")

        @self.api_bp.errorhandler(500)
        async def bad_request_500(e):
            return self.utils.get_return_templates(0, error=f"500：{e}")

    def run(self, debug=False, host='127.0.0.1', port=60053):
        self.app.run(debug=debug, host=host, port=port)

if __name__ == '__main__':
    # _app().run(debug=True)
    _app().run()




