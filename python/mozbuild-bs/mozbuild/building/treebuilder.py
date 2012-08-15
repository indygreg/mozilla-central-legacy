# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this file,
# You can obtain one at http://mozilla.org/MPL/2.0/.

import logging
import os.path
import re
import time
import traceback

from mozbuild.base import Base
from mozbuild.compilation.warnings import WarningsCollector
from mozbuild.compilation.warnings import WarningsDatabase
from mozbuild.configuration.configure import Configure

RE_TIER_DECLARE = re.compile(r'tier_(?P<tier>[a-z]+):\s(?P<directories>.*)')
RE_TIER_ACTION = re.compile(r'(?P<action>[a-z]+)_tier_(?P<tier>[a-z_]+)')

RE_ENTERING_DIRECTORY = re.compile(
    r'^make(?:\[\d+\])?: Entering directory `(?P<directory>[^\']+)')

RE_LEAVING_DIRECTORY = re.compile(
    r'^make(?:\[\d+\])?: Leaving directory `(?P<directory>[^\']+)')


class BuildInvocation(object):
    """Holds state relevant to an individual build invocation.

    Currently, functionality is limited to tracking tier progression.
    Functionality can be expanded to cover all kinds of reporting, as needed.
    """
    def __init__(self):
        self.tier = None
        self.action = None
        self.directories = {}

        self._on_update = []

    def add_listener(self, listener):
        """Registers a listener for this build instance.

        When the build state has changed, the registered function gets called.
        The function receives as named arguments:

        build -- This BuildInvocation instance.
        action -- Single word str describing the action being performed.
        directory -- If a directory state change caused this update, this will
            be the str of the directory that changed.
        """
        self._on_update.append(listener)

    def update_tier(self, tier):
        self.tier = tier
        self.action = 'default'
        self.directories = {}

        self._call_listeners(action='new_tier')

    def update_action(self, tier, action):
        assert tier == self.tier

        self.action = action

        for k in self.directories.iterkeys():
            self.directories[k] = {'start_time': None, 'finish_time': None}

        self._call_listeners(action='new_action')

    def register_directory(self, directory):
        self.directories[directory] = {'start_time': None, 'finish_time': None}

    def set_directory_in_progress(self, directory):
        if not directory in self.directories:
            return

        self.directories[directory]['start_time'] = time.time()

        self._call_listeners(action='directory_start', directory=directory)

    def set_directory_finished(self, directory):
        if not directory in self.directories:
            return

        self.directories[directory]['finish_time'] = time.time()

        self._call_listeners(action='directory_finish', directory=directory)

    def _call_listeners(self, action=None, directory=None):
        for listener in self._on_update:
            listener(build=self, action=action, directory=directory)


class TreeBuilder(Base):
    """Provides a high-level interface for building a tree.

    This currently implements the logic for building with our existing
    configure + recursive make backend. In the future, backends will likely be
    implemented as an interface and multiple backends will be supported. This
    will be a significant change and this class will likely be heavily
    modified, possibly even deleted.
    """

    def build(self, on_update=None):
        """Builds the tree.

        on_update - Function called when the progress of the build has changed.
            This function receives the following named arguments:
                tier - The tier the build is currently in.
                action - The tier action the build is in.
                directories - State of directories in the tier. Dict of str to
                    int. Keys are relative paths in build system. Values are
                    0 for queued, 1 for in progress, and 2 for finished.
        """

        self._ensure_objdir_exists()

        c = self._spawn(Configure)
        c.ensure_configure()

        build = BuildInvocation()
        if on_update:
            build.add_listener(on_update)

        warnings_path = self._get_state_filename('warnings.json')
        warnings_database = WarningsDatabase()

        if os.path.exists(warnings_path):
            warnings_database.load_from_file(warnings_path)

        warnings_collector = WarningsCollector(database=warnings_database,
            objdir=self.objdir)

        def handle_line(line):
            """Callback that receives output from make invocation."""

            match = RE_ENTERING_DIRECTORY.match(line)
            if match:
                directory = match.group('directory')

                # NSS and possibly others rain on our parade.
                if not directory.startswith(self.objdir):
                    return

                relative = directory[len(self.objdir) + 1:]
                build.set_directory_in_progress(relative)
                return

            match = RE_LEAVING_DIRECTORY.match(line)
            if match:
                directory = match.group('directory')

                if not directory.startswith(self.objdir):
                    return

                relative = directory[len(self.objdir) + 1:]
                build.set_directory_finished(relative)
                return

            # We don't log the entering/leaving directory messages because
            # they are spammy. The callback can choose to display something if
            # it really wants.
            self.log(logging.INFO, 'make', {'line': line}, '{line}')

            match = RE_TIER_DECLARE.match(line)
            if match:
                tier = match.group('tier')
                directories = match.group('directories').strip().split()

                build.update_tier(tier)
                for d in directories:
                    build.register_directory(d)

                return

            match = RE_TIER_ACTION.match(line)
            if match:
                build.update_action(match.group('tier'), match.group('action'))
                return

            # Ideally we shouldn't have this. But, if we crash, we shouldn't
            # crash the build. Currently, the only known source of crashing is
            # not finding the file that caused the warning. Unfortunately, this
            # is sometimes due to interleaved output from multiple make child
            # processes, which there is little we can do about.
            try:
                warning = warnings_collector.process_line(line)
                if warning:
                    self.log(logging.INFO, 'compiler_warning', warning,
                        'Warning: {flag} in {filename}: {message}')

            except:
                self.log(logging.WARNING, 'nonfatal_exception',
                        {'exc': traceback.format_exc()},
                        '{exc}')

        self._run_make(line_handler=handle_line, log=False)

        self.log(logging.WARNING, 'warning_summary',
                {'count': len(warnings_collector.database)},
                '{count} compiler warnings')

        warnings_database.save_to_file(warnings_path)

    def build_tier(self, tier=None, action=None):
        """Perform an action on a specific tier."""
        assert tier is not None

        # TODO Capture results like we do for full builds?
        target = 'tier_%s' % tier

        if action is not None and action != 'default':
            target = '%s_%s' % (action, target)

        self._run_make(directory='.', target=target)
