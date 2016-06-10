#
# Copyright (c) 2015-2016 Intel Corporation
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#

import abc
import json
import ssl
import uuid

import requests
from retry import retry

from ..constants import ServiceLabels, ServicePlan
from ..exceptions import UnexpectedResponseError
from ..tap_logger import get_logger, log_http_request, log_http_response
from configuration import config
from ..tap_object_model import ServiceInstance
from ..test_names import generate_test_object_name
from ..websocket_client import WebsocketClient

logger = get_logger(__name__)


def _generate_uuid():
    return str(uuid.uuid4()).replace("-", "")


class JupyterWSBase(metaclass=abc.ABCMeta):
    WS_TIMEOUT = 5  # (seconds) - timeout for unresponsive socket

    def __init__(self, uri, origin, headers, cert_requirement):
        self.ws = WebsocketClient(uri, origin, headers, cert_requirement)

    @abc.abstractmethod
    def _get_command_payload(self, content):
        pass

    def _get_reply_payload(self, content):
        pass

    def send_input(self, content, reply=False, obscure_from_log=False):
        if reply:
            msg = self._get_reply_payload(content)
        else:
            msg = self._get_command_payload(content)
        if obscure_from_log:
            logger.info(msg.replace(content, "[SECRET]"))
        else:
            logger.info(msg)
        self.ws.send(msg)

    def get_output(self):
        """Retrieve all messages"""
        return self.ws.recieve()


class JupyterTerminal(JupyterWSBase):

    def __init__(self, uri, origin, headers, cert_requirement, number):
        super().__init__(uri, origin, headers, cert_requirement)
        self.number = number

    def __repr__(self):
        return "Terminal {}".format(self.number)

    def _get_command_payload(self, msg):
        return json.dumps(["stdin", msg])


class JupyterNotebook(JupyterWSBase):

    def __init__(self, uri, origin, headers, cert_requirement, session_id, path):
        super().__init__(uri, origin, headers, cert_requirement)
        self._session_id = session_id
        self._path = path
        self._last_msg_id = None

    def __repr__(self):
        return "{} (path={}, session_id={})".format(self.__class__.__name__, self._path, self._session_id)

    def _get_command_payload(self, content):
        """Return full message passed as command to Jupyter notebook"""
        self._last_msg_id = _generate_uuid()  # see Jupyter JavaScript static/services/kernels/kernel.js, line 74
        msg = {
            "header": {"msg_id": self._last_msg_id, "username": "username", "session": self._session_id,
                       "msg_type": "execute_request", "version": "5.0"},
            "metadata": {},
            "content": {"code": content, "silent": False, "store_history": True, "user_expressions": {},
                        "allow_stdin": True, "stop_on_error": True},
            "buffers": [],
            "parent_header": {},
            "channel": "shell"
        }
        return json.dumps(msg)

    def _get_reply_payload(self, content):
        """Return full message passed as interactive reply to a prompt"""
        self._last_msg_id = _generate_uuid()  # see Jupyter JavaScript static/services/kernels/kernel.js, line 74
        msg = {
            "header": {"msg_id": self._last_msg_id, "username": "username", "session": self._session_id,
                       "msg_type": "input_reply", "version": "5.0"},
            "metadata": {},
            "content": {"value": content},
            "buffers": [],
            "parent_header": {},
            "channel": "stdin"
        }
        return json.dumps(msg)

    def _get_frames_with_msg_type(self, msg_type):
        output = self.get_output()
        output = [json.loads(item) for item in output]
        return [frame for frame in output if frame["msg_type"] == msg_type]

    def _get_frame_with_msg_type(self, msg_type):
        return next(iter(self._get_frames_with_msg_type(msg_type)))

    def get_command_result(self):
        result_frame = self._get_frame_with_msg_type("execute_request")
        content = result_frame["content"]["data"]["text/plain"]
        return content

    def get_stream_result(self):
        stream_frame = self._get_frames_with_msg_type("stream")
        content = []
        for frame in stream_frame:
            content.append(frame["content"]["text"])
        return content

    def check_command_status(self):
        reply_frame = self._get_frame_with_msg_type("execute_reply")
        status = reply_frame["content"]["status"]
        if status == "error":
            raise AssertionError("{} {} {}".format(self, reply_frame["content"]["ename"],
                                                   reply_frame["content"]["evalue"]))
        return status

    def get_prompt_text(self):
        reply_frame = self._get_frame_with_msg_type("input_request")
        return reply_frame["content"]["prompt"]


class Jupyter(object):
    def __init__(self, org_guid, space_guid, instance_name=None, params=None):
        """Create Jupyter service instance"""
        if instance_name is None:
            instance_name = generate_test_object_name(short=True, prefix=ServiceLabels.JUPYTER)
        self.cookie = None
        self.password = None
        self.instance_url = None
        self.http_session = requests.Session()
        self.ws_sslopt = None
        if not config.CONFIG["ssl_validation"]:
            self.http_session.verify = False
            self.ws_sslopt = ssl.CERT_NONE
        self.instance = ServiceInstance.api_create_with_plan_name(org_guid=org_guid, space_guid=space_guid,
                                                                  name=instance_name,
                                                                  service_label=ServiceLabels.JUPYTER,
                                                                  service_plan_name=ServicePlan.FREE, params=params)

    def __repr__(self):
        return "{} (instance_url={})".format(self.__class__.__name__, self.instance_url)

    def _request(self, method, endpoint, body=None, data=None, params=None, message_on_error=""):
        request = requests.Request(
            method=method,
            url="https://{}/{}".format(self.instance_url, endpoint),
            data=data,
            params=params,
            json=body
        )
        request = self.http_session.prepare_request(request)
        log_http_request(request, username="Jupyter Client", password=self.password)
        response = self.http_session.send(request)
        log_http_response(response)
        if not response.ok:
            raise UnexpectedResponseError(status=response.status_code, error_message=message_on_error)
        self.cookie = ", ".join(["{}={}".format(k, v) for k, v in self.http_session.cookies.get_dict().items()])
        try:
            return json.loads(response.text)
        except ValueError:
            return response.text

    @retry(KeyError, tries=5, delay=5)
    def get_credentials(self):
        response = self.instance.api_get_credentials()
        self.password = response["password"]
        self.instance_url = response["hostname"]

    def login(self):
        self._request(
            method="POST",
            endpoint="login",
            data={"password": self.password},
            params={"next": "/tree"},
            message_on_error="Failed login to Jupyter"
        )

    def connect_to_terminal(self, terminal_no):
        uri = "{}://{}/terminals/websocket/{}".format(WebsocketClient.WSS, self.instance_url, terminal_no)
        origin = "https://{}".format(self.instance_url)
        headers = {"Cookie": self.cookie}
        return JupyterTerminal(uri, origin, headers, self.ws_sslopt, terminal_no)

    def create_notebook(self, python_version=2):
        python_version = "python{}".format(python_version)
        response = self._request(
            method="POST",
            endpoint="api/contents",
            body={"type": "notebook"},
            message_on_error="Could not create notebook"
        )
        notebook_path = response["path"]
        response = self._request(
            method="POST",
            endpoint="api/sessions",
            body={
                "kernel": {"id": None, "name": python_version},
                "notebook": {"path": notebook_path}
            },
            message_on_error="Could not create kernel session for {}".format(python_version)
        )
        kernel_id = response["kernel"]["id"]
        session_id = _generate_uuid()  # see Jupyter JavaScript static/services/kernels/kernel.js, line 42
        uri = "{}://{}/api/kernels/{}/channels?session_id={}".format(WebsocketClient.WSS, self.instance_url, kernel_id,
                                                                     session_id)
        origin = "https://{}".format(self.instance_url)
        headers = {"Cookie": self.cookie}
        return JupyterNotebook(uri, origin, headers, self.ws_sslopt, session_id, notebook_path)
