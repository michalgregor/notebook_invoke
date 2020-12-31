import json
from .encoder import NumpyEncoder
from .invoke_py import (
    _is_google_colab, register_callback,
    remove_callback, jupyter_javascript_routines
)
from IPython.display import display, Javascript
from IPython.core.magic import cell_magic, magics_class, Magics
from IPython import get_ipython
import re

def args2js(args):
    if not isinstance(args, list):
        raise TypeError("Argument 'args': a list is expected.")

    str_args = ["JSON.parse('" + json.dumps(a, cls=NumpyEncoder) + "')" for a in args]
    str_args = ", ".join(str_args)

    return str_args

_re_as_name = re.compile("as ([^\d\W]\w*):?\Z")

@magics_class
class MakeInvokeMagics(Magics):
    @cell_magic
    def make_invoke_context(self, line, cell):
        ctx = InvokeJsContext()
        ctx_name = None

        if line.strip() != '':
            m = _re_as_name.fullmatch(line)

            if m is None:
                raise ValueError("Line '{}' not recognized in magic 'make_invoke_context'.".format(line))
            else:
                ctx_name = m.group(1)
                self.shell.user_ns[ctx_name] = ctx

        with ctx:
            exec(cell, self.shell.user_ns)

        if not ctx_name is None:
            del self.shell.user_ns[ctx_name]

get_ipython().register_magics(MakeInvokeMagics)

# Class taken from https://github.com/kafonek/ipython_blocking (BSD-3)
# with slight modifications.
class CaptureExecution:
    "A context manager to capture execute_request events then either replay or disregard them after exiting the manager"
    def __init__(self, replay=True, continue_on_except=True):
        self.captured_events = []
        self._replay = replay
        self.shell = get_ipython()
        self.kernel = self.shell.kernel
        self.continue_on_except = continue_on_except
        
    def step(self):
        self.kernel.do_one_iteration() 
    
    def capture_event(self, stream, ident, parent):
        "A 'capture' function to register instead of the default execute_request handling"

        # if ignore_capture, replay the event immediately
        if parent['content'].get('ignore_capture', False):
            self.kernel.set_parent(ident, parent) 
            self.kernel.execute_request(stream, ident, parent)
        # or else store it for later
        else:
            self.captured_events.append((stream, ident, parent))

    def start_capturing(self):
        "Overwrite the kernel shell handler to capture instead of executing new cell-execution requests"
        self.kernel.shell_handlers['execute_request'] = self.capture_event

    def stop_capturing(self):
        "revert the kernel shell handler to the default execute_request behavior"
        self.kernel.shell_handlers['execute_request'] = self.kernel.execute_request
    
    def replay_captured_events(self):
        "Called at end of context -- replays all captured events once the default execution handler is in place"
        # need to flush before replaying so messages show up in current cell not replay cells
        sys.stdout.flush()
        sys.stderr.flush()

        for stream, ident, parent in self.captured_events:
            # Using kernel.set_parent is the key to getting the output of the replayed events
            # to show up in the cells that were captured instead of the current cell
            self.kernel.set_parent(ident, parent) 
            self.kernel.execute_request(stream, ident, parent)

    def __enter__(self):
        self.start_capturing()
        self.shell.execution_count += 1 # increment execution count to avoid collision error
        return self
        
    def __exit__(self, exc_type, exc_value, traceback):
        if exc_type is not None and self.continue_on_except:
            # let the error propogate up, such as a keyboard interrupt while capturing cell execution
            return False

        self.stop_capturing()

        if self._replay and exc_type is None:
            self.replay_captured_events()

if _is_google_colab:
    from google.colab.output import eval_js

    def exec_js(expr, args=None):
        """
        Execute javascript asynchronously without capturing the return value.
        """

        if args is None:
            str_args = ''
        else:
            str_args = '(' + args2js(args) + ')'

        display(Javascript(expr + str_args))

    class InvokeJsContext:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_value, traceback):
            pass

        def eval_js_expr(self, expr):
            return eval_js(expr)

        def invoke_js_func(self, func, args=[]):
            str_args = "(" + args2js(args) + ")"
            return eval_js(func + str_args)

else:
    import sys
    import uuid

    _exec_js_display = display(display_id=True)

    def exec_js(expr, args=None):
        """
        Execute javascript asynchronously without capturing the return value.
        """

        if args is None:
            str_args = ''
        else:
            str_args = '(' + args2js(args) + ')'

        _exec_js_display.update(Javascript(expr + str_args))

    class InvokeJsContext(CaptureExecution):
        def __init__(self):
            super().__init__(continue_on_except=False)
            self.id = uuid.uuid1().hex
            self._ret = None
            self._returned = False

            register_callback(
                "_invoke_submit_results_" + self.id,
                self._submit_return
            )

            self.display = display(display_id="_jupyter_invoke_disp_" + self.id)

        def _submit_return(self, ret):
            self._ret = ret
            self._returned = True

        def _invoke_js(self, expr, as_func, args=[]):
            if as_func:
                str_args = "(" + args2js(args) + ")"
            else:
                str_args = ""

            self.display.update(Javascript(
                jupyter_javascript_routines + """
                const ret = {{expr}}{{str_args}};
                invoke_function('_invoke_submit_results_{{UUID}}', [ret], {});
                """.replace(
                    "{{expr}}", expr
                ).replace(
                    "{{str_args}}", str_args
                ).replace(
                    "{{UUID}}", self.id
                )
            ))

            while True:
                if self._returned:
                    ret = self._ret
                    self._ret = None
                    self._returned = False
                    return ret

                self.step()
        
        def eval_js_expr(self, expr):
            return self._invoke_js(expr, as_func=False)

        def invoke_js_func(self, func, args=[]):
            return self._invoke_js(func, as_func=True, args=args)

        def __del__(self):
            remove_callback("_invoke_submit_results_" + self.id)
