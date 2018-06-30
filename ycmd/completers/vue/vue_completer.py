from __future__ import unicode_literals
from __future__ import print_function
from __future__ import division
from __future__ import absolute_import

from builtins import *

import logging
import os
import threading
from subprocess import PIPE

from ycmd import utils, responses
from ycmd.completers.language_server import language_server_completer

_logger = logging.getLogger(__name__)

NO_DOCUMENTATION_MESSAGE = 'No documentation available for current context'
LANGUAGE_SERVER_HOME = os.path.abspath(
    os.path.join(
        os.path.dirname(__file__), '..', '..', '..', 'third_party', 'vls',
        'node_modules', '.bin', 'vls'))

PATH_TO_NODE = utils.PathToFirstExistingExecutable(['node'])


def ShouldEnableVueCompleter():
    _logger.info('Looking for vls')
    if not PATH_TO_NODE:
        _logger.warning('Not enabling vue completion: Could not find nodejs')
        return False

    if not os.path.exists(LANGUAGE_SERVER_HOME):
        _logger.warning('Not enabling vue completion: Vls is not installed')

    return True


class VueCompleter(language_server_completer.LanguageServerCompleter):
    def __init__(self, user_options):
        super(VueCompleter, self).__init__(user_options)

        self._server_keep_logfiles = user_options['server_keep_logfiles']
        self._server_state_mutex = threading.RLock()

        self._server_stderr = None

        self._CleanUp()

    def SupportedFiletypes(self):
        return ['vue']

    def GetSubcommandsMap(self):
        return {
          # Handled by base class
          'GoToDeclaration': (
            lambda self, request_data, args: self.GoToDeclaration( request_data )
          ),
          'GoTo': (
            lambda self, request_data, args: self.GoToDeclaration( request_data )
          ),
          'GoToDefinition': (
            lambda self, request_data, args: self.GoToDeclaration( request_data )
          ),
          'GoToReferences': (
            lambda self, request_data, args: self.GoToReferences( request_data )
          ),
          'FixIt': (
            lambda self, request_data, args: self.GetCodeActions( request_data,
                                                                  args )
          ),
          'RefactorRename': (
            lambda self, request_data, args: self.RefactorRename( request_data,
                                                                  args )
          ),
          'Format': (
            lambda self, request_data, args: self.Format( request_data )
          ),

          # Handled by us
          'RestartServer': (
            lambda self, request_data, args: self._RestartServer( request_data )
          ),
          'StopServer': (
            lambda self, request_data, args: self._StopServer()
          ),
          # 'GetDoc': (
          #   lambda self, request_data, args: self.GetDoc( request_data )
          # ),
          # 'GetType': (
          #   lambda self, request_data, args: self.GetType( request_data )
          # ),
        }

    def OnFileReadyToParse(self, request_data):
        self._StartServer(request_data)
        return super(VueCompleter, self).OnFileReadyToParse(request_data)

    def DebugInfo(self, request_data):
        items = [
            responses.DebugInfoItem('Startup Status', self._server_init_status)
        ]

        return responses.BuildDebugInfoResponse(
            name="Vue",
            servers=[
                responses.DebugInfoServer(
                    name="Vue Language Server",
                    handle=self._server_handle,
                    executable=LANGUAGE_SERVER_HOME,
                    logfiles=[self._server_stderr],
                    extras=items)
            ])

    def GetConnection(self):
        return self._connection

    def HandleServerCommand(self, request_data, command):
        return None

    def Shutdown(self):
        self._StopServer()

    def ServerIsHealthy(self):
        return self._ServerIsRunning()

    def ServerIsReady(self):
        return self.ServerIsHealthy() and super(VueCompleter, self).ServerIsReady()

    def HandleNotificationInPollThread(self, notification):
        super(VueCompleter, self).HandleNotificationInPollThread(notification)

    def ConvertNotificationToMessage(self, request_data, notification):
        return super(VueCompleter, self).ConvertNotificationToMessage(
            request_data, notification)

    def _CleanUp(self):
        _logger.info('+++++++++++cleanup vls')
        if not self._server_keep_logfiles:
            if self._server_stderr:
                utils.RemoveIfExists(self._server_stderr)
                self._server_stderr = None

        self._received_ready_message = threading.Event()
        self._project_dir = None
        self._server_init_status = 'Not started'
        self._server_started = False
        self._server_handle = None
        self._connection = None

        self.ServerReset()

    def _ServerIsRunning(self):
        return utils.ProcessIsRunning(self._server_handle)

    def _StartServer(self, request_data):
        with self._server_state_mutex:
            if self._server_started:
                return

            self._server_started = True
            _logger.info('Starting Vue Language Server')

            command = [LANGUAGE_SERVER_HOME, '--stdio']

            self._server_stderr = utils.CreateLogfile('vls_stderr_')

            with utils.OpenForStdHandle(self._server_stderr) as stderr:
                self._server_handle = utils.SafePopen(
                    command, stdin=PIPE, stdout=PIPE, stderr=stderr)

            if not self._ServerIsRunning():
                _logger.error('Vue Language Server failed to start')
                return

            _logger.info('Vue Language Server started')

            self._connection = language_server_completer.StandardIOLanguageServerConnection(
                self._server_handle.stdin, self._server_handle.stdout,
                self.GetDefaultNotificationHandler())

            self._connection.Start()

            try:
                self._connection.AwaitServerConnection()
            except language_server_completer.LanguageServerConnectionTimeout:
                _logger.error(
                    'Vue Language Server failed to start, or did not connect successfully'
                )
                self._StopServer()
                return

            self.SendInitialize(request_data)

    def _StopServer(self):
        with self._server_state_mutex:
            _logger.info('Shutting down vls...')

            if self._server_handle and self._server_handle.stderr:
                self._server_handle.stderr.close()

            if self._connection:
                self._connection.Stop()

            if not self._ServerIsRunning():
                _logger.info('Vue Language Server not running')
                self._CleanUp()
                return

            _logger.info('Stopping Vls with PID {0}'.format(
                self._server_handle.pid))

            try:
                self.ShutdownServer()
                if self._connection:
                    self._connection.Close()

                utils.WaitUntilProcessIsTerminated(
                    self._server_handle, timeout=15)
            except Exception:
                _logger.exception('Error while stopping Vue Language Server')

            self._CleanUp()

    def _RestartServer(self, request_data):
        with self._server_state_mutex:
            self._StopServer()
            self._StartServer(request_data)
