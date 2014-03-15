import threading
import datetime
import json
import pydle

try:
    from unittest.mock import Mock
except:
    from mock import Mock


class MockServer:
    """
    A mock server that will receive data and messages from the client,
    and can send its own data and messages.
    """

    def __init__(self):
        self.connection = None
        self.recvbuffer = ''
        self.msgbuffer = []

    def receive(self, *args, **kwargs):
        self.msgbuffer.append((args, kwargs))

    def receivedata(self, data):
        self.recvbuffer += data

    def received(self, *args, **kwargs):
        if (args, kwargs) in self.msgbuffer:
            self.msgbuffer.remove((args, kwargs))
            return True
        return False

    def receiveddata(self, data):
        if data in self.recvbuffer:
            self.recvbuffer.replace(data, '', 1)
            return True
        return False

    def send(self, *args, **kwargs):
        msg = self.connection._mock_client._create_message(*args, **kwargs)
        self.connection._mock_client.on_raw(msg)

    def sendraw(self, data):
        self.connection._mock_client.on_data(data)


class MockClient(pydle.client.BasicClient):
    """ A client that subtitutes its own connection for a mock connection to MockServer. """

    def __init__(self, *args, mock_server=None, **kwargs):
        self._mock_server = mock_server
        self._mock_logger = Mock()
        super().__init__(*args, **kwargs)

    @property
    def logger(self):
        return self._mock_logger

    @logger.setter
    def logger(self, val):
        pass

    def _connect(self, hostname, port, *args, **kwargs):
        self.connection = MockConnection(hostname, port, mock_client=self, mock_server=self._mock_server, eventloop=self.eventloop)
        self.connection.connect()

    def raw(self, data):
        self.connection._mock_server.receivedata(data)

    def rawmsg(self, *args, **kwargs):
        self.connection._mock_server.receive(*args, **kwargs)

    def _create_message(self, *args, **kwargs):
        return MockMessage(*args, **kwargs)

    def _has_message(self):
        return b'\r\n' in self._receive_buffer

    def _parse_message(self):
        message, _, data = self._receive_buffer.partition(b'\r\n')
        self._receive_buffer = data
        return MockMessage.parse(message + b'\r\n', encoding=self.encoding)


class MockConnection(pydle.connection.Connection):
    """ A mock connection between a client and a server. """

    def __init__(self, *args, mock_client=None, mock_server=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._mock_connected = False
        self._mock_server = mock_server
        self._mock_client = mock_client

    def on(self, *args, **kwargs):
        pass

    def off(self, *args, **kwargs):
        pass

    @property
    def connected(self):
        return self._mock_connected

    def connect(self, *args, **kwargs):
        self._mock_server.connection = self
        self._mock_connected = True

    def disconnect(self, *args, **kwargs):
        self._mock_server.connection = None
        self._mock_connected = False


class MockEventLoop:
    """ A mock event loop for use in testing. """

    def __init__(self, *args, **kwargs):
        self._mock_timers = {}
        self._mock_periodical_id = 0
        self.running = False

    def __del__(self):
        pass

    def run(self):
        self.running = True

    def run_with(self, func):
        self.running = True
        func()
        self.stop()

    def run_until(self, future):
        self.running = True
        future.result()
        self.stop()

    def stop(self):
        self.running = False
        for timer in self._mock_timers.values():
            timer.cancel()

    def schedule(self, f, *args, **kwargs):
        f(*args, **kwargs)

    def schedule_in(self, _delay, _f, *_args, **_kw):
        if isinstance(_delay, datetime.timedelta):
            _delay = _delay.total_seconds()

        timer = threading.Timer(_delay, _f, _args, _kw)
        timer.start()

        id = self._mock_periodical_id
        self._mock_timers[id] = timer
        self._mock_periodical_id += 1
        return id

    def schedule_periodically(self, _delay, _f, *_args, **_kw):
        if isinstance(_delay, datetime.timedelta):
            _delay = _delay.total_seconds()

        id = self._mock_periodical_id
        timer = threading.Timer(_delay, self._do_schedule_periodically, (_f, _delay, id, _args, _kw))
        timer.start()

        self._mock_timers[id] = timer
        self._mock_periodical_id += 1
        return id

    def _do_schedule_periodically(self, f, delay, id, args, kw):
        if not self.is_scheduled(id):
            return

        timer = threading.Timer(delay, self._do_schedule_periodically, (f, delay, id, args, kw))
        timer.start()
        self._mock_timers[id] = timer
        result = False

        try:
            result = f(*args, **kw)
        finally:
            if result == False:
                self.unschedule(id)

    def is_scheduled(self, handle):
        return handle in self._mock_timers

    def unschedule(self, handle):
        self._mock_timers[handle].cancel()
        del self._mock_timers[handle]


class MockMessage(pydle.protocol.Message):
    def __init__(self, command, *params, source=None, **kw):
        self.command = command
        self.params = params
        self.source = source
        self.kw = kw
        self._valid = True

    @classmethod
    def parse(cls, line, encoding=pydle.protocol.DEFAULT_ENCODING):
        # Decode message.
        line = line.strip()
        try:
            message = line.decode(encoding)
        except UnicodeDecodeError:
            # Try our fallback encoding.
            message = line.decode(pydle.protocol.FALLBACK_ENCODING)

        try:
            val = json.loads(message)
        except:
            raise pydle.protocol.ProtocolViolation('Invalid JSON')

        return MockMessage(val['command'], *val['params'], source=val['source'], **val['kw'])

    def construct(self):
        return json.dumps({ 'command': self.command, 'params': self.params, 'source': self.source, 'kw': self.kw }) + '\r\n'
