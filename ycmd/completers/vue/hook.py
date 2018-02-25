from __future__ import unicode_literals
from __future__ import print_function
from __future__ import division
from __future__ import absolute_import

from builtins import *

from ycmd.completers.vue.vue_completer import ( ShouldEnableVueCompleter, VueCompleter )

def GetCompleter(user_options):
    if not ShouldEnableVueCompleter():
        return None

    return VueCompleter(user_options)
