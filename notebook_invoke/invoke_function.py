import json
from .encoder import NumpyEncoder
_jupyter_javascript_callbacks = globals()['_jupyter_javascript_callbacks'] = {}

def register_callback(callback_id, callback):
    _jupyter_javascript_callbacks[callback_id] = callback

try:
    import google.colab.output

    def invoke_wrapper(func_id, *args, **kwargs):
        func = _jupyter_javascript_callbacks[func_id]
        ret = func(*args, **kwargs)
        return json.dumps(ret, cls=NumpyEncoder)

    google.colab.output.register_callback("invoke_wrapper", invoke_wrapper)
        
    jupyter_javascript_routines = r"""
    function invoke_function(func, args, kwargs) {
        return google.colab.kernel.invokeFunction("invoke_wrapper", [func].concat(args), kwargs).then(
            function(response) {
                var output = response.data["text/plain"];
                output = output.substring(1, output.length-1).replace("\\'","'");
                return JSON.parse(output);
            }
        );
    }
    """

except ModuleNotFoundError:
    def invoke_wrapper(func_id, argsjson=None, kwjson=None):
        func = _jupyter_javascript_callbacks[func_id]

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
    function handle_io(response) {
        if(response.msg_type == "stream" &&
            response.content.name == "stdout")
        {
            element.append("<pre>" + response.content.text + "</pre>");
        }

        if(response.msg_type == "error")
        {
            element.append("<pre>" + response.content.evalue + "</pre>");
        }
    }

    Jupyter.notebook.kernel.execute('from notebook_invoke import invoke_wrapper as _jupyter_invoke_wrapper', {iopub: {output: handle_io}});

    function invoke_function(func, args, kwargs) {
        return new Promise((resolve, reject) => {
            function handle_output(response) {
                if(response.msg_type == "stream" &&
                   response.content.name == "stdout")
                {
                    element.append("<pre>" + response.content.text + "</pre>");
                }

                if(response.msg_type == "error")
                {
                    element.append("<pre>" + response.content.evalue + "</pre>");
                }

                if(response.msg_type == "execute_result") {
                    var output = response.content.data["text/plain"];
                    output = output.substring(1, output.length-1).replace("\\'","'");
                    var data = JSON.parse(output);
                    resolve(data);
                }
            }

            Jupyter.notebook.kernel.execute(
                `_jupyter_invoke_wrapper('${func}', '${JSON.stringify(args)}', '${JSON.stringify(kwargs)}')`,
                {iopub: {output: handle_output}},
                {silent: false, store_history: false, stop_on_error: true}
            );
        });
    }
    """
    