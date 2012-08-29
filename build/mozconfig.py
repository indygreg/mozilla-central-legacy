import imp, os, sys

path = os.path.dirname(__file__)
while not os.path.exists(os.path.join(path, 'config.status')):
    parent = os.path.normpath(os.path.join(path, '..'))
    if parent == path:
        raise Exception, '''Can't find config.status'''
    path = parent

path = os.path.join(path, 'config.status')
config = imp.load_module('_mozconfig', open(path), path, ('', 'r', imp.PY_SOURCE))

for var in config.__all__:
    value = getattr(config, var)
    if isinstance(value, list) and isinstance(value[0], tuple):
        value = dict(value)
    setattr(sys.modules[__name__], var, value)
