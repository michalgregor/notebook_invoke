import json
import types
from weakref import ref, WeakMethod
from .encoder import NumpyEncoder
_jupyter_javascript_callbacks = globals()['_jupyter_javascript_callbacks'] = {}

def register_callback(callback_id, callback):
    if isinstance(callback, types.MethodType):
        _jupyter_javascript_callbacks[callback_id] = WeakMethod(callback)
    else:
        _jupyter_javascript_callbacks[callback_id] = ref(callback)

def remove_callback(callback_id):
    del _jupyter_javascript_callbacks[callback_id]

try:
    import google.colab.output
    _is_google_colab = True

    def invoke_wrapper(func_id, *args, **kwargs):
        func = _jupyter_javascript_callbacks[func_id]()
        ret = func(*args, **kwargs)
        return json.dumps(ret, cls=NumpyEncoder)

    google.colab.output.register_callback("invoke_wrapper", invoke_wrapper)

    jupyter_javascript_routines = r"""
    var _init_promise = new Promise((resolve, reject) => {
        resolve(true);
    });

    function invoke_function(func, args, kwargs, execute_after=null) {
        if(execute_after === null) execute_after = _init_promise;
        
        return new Promise((resolve, reject) => {
            execute_after.then(run_args => {
                google.colab.kernel.invokeFunction("invoke_wrapper", [func].concat(args), kwargs).then(
                    function(msg) {
                        var output = msg.data["text/plain"];
                        output = output.substring(1, output.length-1).replace("\\'","'");
                        resolve(JSON.parse(output));
                    }
                );
            });
        });
    }
    """

except ModuleNotFoundError:
    _is_google_colab = False

    def invoke_wrapper(func_id, argsjson=None, kwjson=None):
        func = _jupyter_javascript_callbacks[func_id]()

        if argsjson:
            args = json.loads(argsjson)
        else:
            args = ()

        if kwjson:
            kwargs = json.loads(kwjson)
        else:
            kwargs = {}

        ret = func(*args, **kwargs)
        return json.dumps(ret, cls=NumpyEncoder)
        
    jupyter_javascript_routines = r"""
    const self = this;

    function _get_callbacks() {
        var cell_element = self.element.parents('.cell');
        var cell_idx = Jupyter.notebook.get_cell_elements().index(cell_element);
        var cell = Jupyter.notebook.get_cell(cell_idx);
        return cell.get_callbacks();
    }

    function _copy_callbacks() {
        const callbacks = _get_callbacks(self.element);
        var cbcopy = {};
        
        // copy all
        for(var key in callbacks) {cbcopy[key] = callbacks[key];}
        const iopub_callbacks = callbacks['iopub'];
        var iopub_cbcopy = cbcopy['iopub'] = {};
        for(var key in iopub_callbacks) {iopub_cbcopy[key] = iopub_callbacks[key];}
        
        return cbcopy;
    }

    // if make_handle_output is not null, code must return a value
    function _run_code(code, make_handle_output=null) {
        if(make_handle_output !== null) {
            var callbacks = _copy_callbacks();
            const handle_output = make_handle_output(callbacks['iopub']['output']);
            callbacks['iopub']['output'] = handle_output;
        } else {
            const callbacks = _get_callbacks();
        }

        Jupyter.notebook.kernel.execute(
            code, callbacks, {silent:false, store_history: false,
            stop_on_error: true, ignore_capture: true}
        );
    }

    function make_handle_output(base_handle_output, resolve=null, reject=null) {
        var returned_once = false;

        function handle_output(msg) {                    
            if(!returned_once && msg.msg_type == "execute_result") {
                returned_once = true;
                var output = msg.content.data["text/plain"];
                output = output.substring(1, output.length-1).replace("\\'","'");
                var data = JSON.parse(output);
                if(resolve !== null) resolve(data);
            } else if(!returned_once && msg.msg_type == "error") {
                if(reject !== null) reject(msg);
                return base_handle_output(msg);
            } else {
                return base_handle_output(msg);
            }
        }

        return handle_output;
    }

    var _init_promise = new Promise((resolve, reject) => {
        _run_code(
            `from notebook_invoke import invoke_wrapper as _jupyter_invoke_wrapper; (lambda: 'true')()`,
            base_handle_output => {
                return make_handle_output(base_handle_output, resolve, reject);
            }
        );
    });

    function invoke_function(func, args, kwargs, execute_after=null) {
        if(execute_after === null) execute_after = _init_promise;

        return new Promise((resolve, reject) => {
            execute_after.then(run_args => {
                _run_code(
                    `_jupyter_invoke_wrapper('${func}', '${JSON.stringify(args)}', '${JSON.stringify(kwargs)}')`,
                    base_handle_output => {
                        return make_handle_output(base_handle_output, resolve, reject);
                    }
                );
            });
        });
    }
    """
    