# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this file,
# You can obtain one at http://mozilla.org/MPL/2.0/.

import logging
import multiprocessing
import os
import shlex
import subprocess

from mozprocess.processhandler import ProcessHandlerMixin

from mozbuild.config import ConfigProvider

# Perform detection of operating system environment. This is used by command
# execution. We only do this once to save redundancy. Yes, this can fail module
# loading. That is arguably OK.
if 'SHELL' in os.environ:
    _current_shell = os.environ['SHELL']
elif 'MOZILLABUILD' in os.environ:
    _current_shell = os.environ['MOZILLABUILD'] + '/msys/bin/sh.exe'
elif 'COMSPEC' in os.environ:
    _current_shell = os.environ['COMSPEC']
else:
    raise Exception('Could not detect environment shell!')

_in_msys = False

if os.environ.get('MSYSTEM', None) == 'MINGW32':
    _in_msys = True

    if not _current_shell.lower().endswith('.exe'):
        _current_shell += '.exe'


class Base(object):
    """Base class providing basic functionality useful for many modules.

    Many modules typically require common functionality, such as accessing the
    current config, getting the location of the source directory, running
    processes, etc. This class provides that functionality. Other modules can
    inherit from this class to obtain this functionality easily.
    """
    def __init__(self, settings, log_manager):
        self.settings = settings
        self.config = BuildConfig(settings)
        self.logger = logging.getLogger(__name__)
        self.log_manager = log_manager

    @property
    def srcdir(self):
        return self.settings.paths.source_directory

    @property
    def objdir(self):
        return self.settings.paths.object_directory

    @property
    def distdir(self):
        return os.path.join(self.objdir, 'dist')

    @property
    def bindir(self):
        return os.path.join(self.objdir, 'dist', 'bin')

    @property
    def statedir(self):
        return os.path.join(self.objdir, '.mozbuild')

    def log(self, level, action, params, format_str):
        self.logger.log(level, format_str,
                        extra={'action': action, 'params': params})

    def _ensure_objdir_exists(self):
        if os.path.isdir(self.statedir):
            return

        os.makedirs(self.statedir)

    def _ensure_state_subdir_exists(self, subdir):
        path = os.path.join(self.statedir, subdir)

        if os.path.isdir(path):
            return

        os.makedirs(path)

    def _get_state_filename(self, filename, subdir=None):
        path = self.statedir

        if subdir:
            path = os.path.join(path, subdir)

        return os.path.join(path, filename)

    def _get_srcdir_path(self, path):
        """Convert a relative path in the source directory to a full path."""
        return os.path.join(self.srcdir, path)

    def _get_objdir_path(self, path):
        """Convert a relative path in the object directory to a full path."""
        return os.path.join(self.objdir, path)

    def _run_make(self, directory=None, filename=None, target=None, log=True,
            srcdir=False, allow_parallel=True, line_handler=None, env=None,
            ignore_errors=False):
        """Invoke make.

        directory -- Relative directory to look for Makefile in.
        filename -- Explicit makefile to run.
        target -- Makefile target(s) to make. Can be a string or iterable of
            strings.
        srcdir -- If True, invoke make from the source directory tree.
            Otherwise, make will be invoked from the object directory.
        """
        self._ensure_objdir_exists()

        args = []

        if directory:
            args.extend(['-C', directory])

        if filename:
            args.extend(['-f', filename])

        if allow_parallel:
            args.append('-j%d' % (self.settings.build.threads + 2))

        if ignore_errors:
            args.append('-k')

        # Silent mode by default.
        args.append('-s')

        # Print entering/leaving directory messages. Some consumers look at
        # these to measure progress. Ideally, we'd do everything with pymake
        # and use hooks in its API. Unfortunately, it doesn't provide that
        # feature... yet.
        args.append('-w')

        if isinstance(target, list):
            args.extend(target)
        elif target:
            args.append(target)

        # Run PyMake on Windows. Run Make everywhere else. We would ideally run
        # PyMake everywhere. Maybe in the future.
        if self._is_windows():
            # We invoke pymake as a sub-process. Ideally, we would import the
            # module and make a method call. Unfortunately, the PyMake API
            # doesn't easily support this.
            path = os.path.join(self.settings.paths.source_directory, 'build',
                    'pymake', 'make.py')

            args.insert(0, path)
        else:
            args.insert(0, 'make')

        fn = self._run_command_in_objdir

        if srcdir:
            fn = self._run_command_in_srcdir

        params = {
            'args': args,
            'line_handler': line_handler,
            'env': env,
            'log_level': logging.INFO,
            'require_unix_environment': True,
            'ignore_errors': ignore_errors,
        }

        if log:
            params['log_name'] = 'make'

        fn(**params)

    def _run_command_in_srcdir(self, **args):
        self._run_command(cwd=self.srcdir, **args)

    def _run_command_in_objdir(self, **args):
        self._run_command(cwd=self.objdir, **args)

    def _run_command(self, args=None, cwd=None, env=None, explicit_env=None,
                     log_name=None, log_level=logging.INFO, line_handler=None,
                     require_unix_environment=False, ignore_errors=False):
        """Runs a single command to completion.

        Takes a list of arguments to run where the first item is the
        executable. Runs the command in the specified directory and
        with optional environment variables.

        env -- Dict of environment variables to append to the current set of
            environment variables.
        explicit_env -- Dict of environment variables to set for the new
            process. Any existing environment variables will be ignored.

        require_unix_environment if True will ensure the command is executed
        within a UNIX environment. Basically, if we are on Windows, it will
        execute the command via an appropriate UNIX-like shell.
        """
        assert isinstance(args, list) and len(args) > 0

        if require_unix_environment and _in_msys:
            # Always munge Windows-style into Unix style for the command.
            prog = args[0].replace('\\', '/')

            # PyMake removes the C: prefix. But, things seem to work here
            # without it. Not sure what that's about.

            # We run everything through the msys shell. We need to use
            # '-c' and pass all the arguments as one argument because that is
            # how sh works.
            cline = subprocess.list2cmdline([prog] + args[1:])
            args = [_current_shell, '-c', cline]

        self.log(logging.INFO, 'process', {'args': args}, ' '.join(args))

        def handleLine(line):
            if line_handler:
                line_handler(line)

            if not log_name:
                return

            self.log(log_level, log_name, {'line': line.strip()}, '{line}')

        use_env = {}
        if explicit_env:
            use_env = explicit_env
        else:
            use_env.update(os.environ)

            if env:
                use_env.update(env)

        p = ProcessHandlerMixin(args, cwd=cwd, env=use_env,
                processOutputLine=[handleLine], universal_newlines=True)
        p.processOutput()
        status = p.waitForFinish()

        if status != 0 and not ignore_errors:
            raise Exception('Process executed with non-0 exit code: %s' % args)

    def _is_windows(self):
        return os.name in ('nt', 'ce')

    def _find_executable_in_path(self, name):
        """Implementation of which.

        Attempts to find the location of an executable in the environment's
        configured paths. The argument can be a single str or a list of str. If
        a list of str, we attempt to find each program name in the environment.
        We first try all locations for the first element, then try all
        locations for the second element, etc.

        None is returned if the executable could not be found.
        """

        candidates = name
        if isinstance(name, str):
            candidates = [name]

        for candidate in candidates:
            for base in os.environ.get('PATH', '').split(os.path.pathsep):
                path = os.path.join(base, candidate)

                if os.path.isfile(path) and os.access(path, os.X_OK):
                    return path

        return None

    def _spawn(self, cls):
        """Create a new Base-derived class instance from ourselves.

        This is used as a convenience method to create other Base-derived class
        instances. It can only be used on classes that have the same
        constructor arguments as Base.
        """

        return cls(self.settings, self.log_manager)


class BuildConfig(ConfigProvider):
    """Represents a configuration for the build environment."""

    def __init__(self, settings):
        self.settings = settings

    @property
    def configure_args(self):
        """Returns list of configure arguments for this configuration."""
        args = []

        args.append('--enable-application=%s' % (
            self.settings.build.application))

        # TODO should be conditional on DirectX SDK presence
        if os.name == 'nt':
            args.append('--disable-angle')

        if self.settings.build.debug:
            args.append('--enable-debug')

        if self.settings.build.optimized:
            args.append('--enable-optimize')

        if self.settings.build.osx_sdk_path:
            args.append('--with-macos-sdk=%s' % self.settings.build.osx_sdk_path)

        if self.settings.build.configure_extra:
            args.extend(shlex.split(self.settings.build.configure_extra))

        return args

    def populate_default_paths(self, source_dir):
        assert os.path.isabs(source_dir)

        self.settings.paths.source_directory = source_dir
        self.settings.paths.object_directory = os.path.join(source_dir,
            'objdir')

    def get_environment_variables(self):
        env = {}

        mapping = {
            ('compiler', 'cc'): 'CC',
            ('compiler', 'cxx'): 'CXX',
            ('compiler', 'cflags'): 'CFLAGS',
            ('compiler', 'cxxflags'): 'CXXFLAGS',
        }

        for (section, option), k in mapping.iteritems():
            value = self.settings[section][option]

            if value:
                env[k] = value

        return env

    @classmethod
    def _register_settings(cls):
        def register(section, option, type, **kwargs):
            cls.register_setting(section, option, type, domain='mozbuild',
                **kwargs)

        register('paths', 'source_directory', ConfigProvider.TYPE_ABSOLUTE_PATH)

        register('paths', 'object_directory', ConfigProvider.TYPE_ABSOLUTE_PATH)

        register('build', 'application', ConfigProvider.TYPE_STRING,
            choices=set(['browser', 'mail', 'suite', 'calendar', 'xulrunner']),
            default='browser')

        register('build', 'threads',
            ConfigProvider.TYPE_POSITIVE_INTEGER,
            default=multiprocessing.cpu_count())

        register('build', 'configure_extra', ConfigProvider.TYPE_STRING,
            default='')

        register('build', 'debug', ConfigProvider.TYPE_BOOLEAN,
            default=False)

        register('build', 'optimized', ConfigProvider.TYPE_BOOLEAN,
            default=True)

        register('build', 'osx_sdk_path', ConfigProvider.TYPE_ABSOLUTE_PATH,
            default=None)

        register('compiler', 'cc', ConfigProvider.TYPE_ABSOLUTE_PATH,
            default=None)

        register('compiler', 'cflags', ConfigProvider.TYPE_STRING,
            default=None)

        register('compiler', 'cxx', ConfigProvider.TYPE_ABSOLUTE_PATH,
            default=None)

        register('compiler', 'cxxflags', ConfigProvider.TYPE_STRING,
            default=None)

