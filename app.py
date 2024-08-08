import base64
import ipaddress
import json
import os

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

        self.config = {}
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
                    with open(file_path, 'r', encoding='utf-8') as file:
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

    async def filter_ip_list(self, ip_list, qax_ti_key=None):
        result = {ip: {
            "whiteIp": ip in self.ipaddress_white_list,
            "blackIp": ip in self.ipaddress_black_list,
            "ipData": {},
            "qaxTi": {}
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

        @self.app.route('/')
        async def home():
            qax_ti_key = request.cookies.get('qax_ti_key', None)
            carry_data = request.cookies.get('carry_data', None)

            bk_lock = self.utils.config['bk_lock']
            bk_url = url_for('static', filename='bk3.jpg') if bk_lock else self.utils.config['bk_url']

            return await render_template("index.html",
                                         qax_ti_key=qax_ti_key,
                                         carry_data=carry_data,
                                         bk_url=bk_url,
                                         bk_lock=bk_lock,
                                         config=self.utils.config,
                                         bullets=Bullets.get_subclasses_name()
                                         )

    def __blueprint_register(self):

        @self.api_bp.route("/process_ips", methods=['POST'])
        async def api_process_ips():
            qax_ti_key = request.headers.get('x-qax-key', None)

            data = await request.get_json()
            bs4_ips = data.get("data", None)
            if bs4_ips:
                ip_input = base64.b64decode(bs4_ips).decode('utf-8')
                ip_lines = [ip.strip() for ip in ip_input.split('\n') if ip.strip()]
                ips_set = set()
                for ip_line in ip_lines:
                    for ip in ip_line.split(','):
                        if self.utils.is_valid_ip(ip):
                            ips_set.add(ip.strip())
                        else:
                            return jsonify(self.utils.get_return_templates(0, error="输入的ip有误"))

                ips = list(ips_set)

                ips_filter_result = await self.utils.filter_ip_list(ips, qax_ti_key)

                response = await make_response(self.utils.get_return_templates(1, data=ips_filter_result))
                if qax_ti_key:
                    response.set_cookie('qax_ti_key', qax_ti_key)
                else:
                    response.set_cookie('qax_ti_key', '', expires=0)

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
                response.set_cookie("carry_data", json.dumps(bullet_info['data']))
            else:
                response.set_cookie("carry_data", "", expires=0)
            return response

        self.app.register_blueprint(self.api_bp, url_prefix='/api')

    def run(self, debug=False, host='127.0.0.1', port=60053):
        self.app.run(debug=debug, host=host, port=port)

if __name__ == '__main__':
    _app().run(debug=True)




