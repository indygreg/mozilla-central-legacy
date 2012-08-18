# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this file,
# You can obtain one at http://mozilla.org/MPL/2.0/.

import logging
import os.path
import re
import time
import traceback

from contextlib import contextmanager

from mozbuild.backend.manager import BackendManager
from mozbuild.base import Base
from mozbuild.compilation.warnings import WarningsCollector
from mozbuild.compilation.warnings import WarningsDatabase
from mozbuild.configuration.configure import Configure
from mozbuild.util import SystemResourceMonitor

RE_TIER_DECLARE = re.compile(r'tier_(?P<tier>[a-z]+):\s(?P<directories>.*)')
RE_TIER_ACTION = re.compile(r'(?P<action>[a-z]+)_tier_(?P<tier>[a-z_]+)')

RE_ENTERING_DIRECTORY = re.compile(
    r'^make(?:\[\d+\])?: Entering directory `(?P<directory>[^\']+)')

RE_LEAVING_DIRECTORY = re.compile(
    r'^make(?:\[\d+\])?: Leaving directory `(?P<directory>[^\']+)')


class TreeBuilder(Base):
    """Provides a high-level interface for building a tree."""

    def build(self, on_phase=None, on_backend=None):
        """Builds the tree."""

        # We wrap the entire build in a resource monitor so we can capture
        # useful data.
        resource_monitor = SystemResourceMonitor()
        resource_monitor.start()
        try:
            self._build(resource_monitor, on_phase, on_backend)
        finally:
            resource_monitor.stop()

            def record_time(name, start, end):
                self.log(logging.INFO, 'phase_time', {
                    'name': name,
                    'start': start,
                    'end': end,
                    'elapsed': end - start,
                }, '{name} Time - {elapsed}s')

            def record_cpu(name, cpu):
                if cpu is None:
                    return

                self.log(logging.INFO, 'cpu_usage', {
                    'name': name,
                    'cores': cpu,
                    'total': sum(cpu) / len(cpu),
                }, '{name} CPU - Average CPU Usage: {total}%')

            def record_io(name, io):
                if io is None:
                    return

                self.log(logging.INFO, 'io_usage', {
                    'name': name,
                    'read_count': io.read_count,
                    'write_count': io.write_count,
                    'read_bytes': io.read_bytes,
                    'write_bytes': io.write_bytes,
                    'read_time': io.read_time,
                    'write_time': io.write_time,
                }, '{name} I/O - Reads: {read_count}; Writes: {write_count}; '
                   'Read Bytes: {read_bytes}; Write Bytes: {write_bytes}; '
                   'Read Time (ms): {read_time}; Write time (ms): {write_time}')

            record_time('total', resource_monitor.start_time,
                resource_monitor.end_time)
            record_cpu('total', resource_monitor.aggregate_cpu())
            record_io('total', resource_monitor.aggregate_io())

            for phase, (start, end) in resource_monitor.phases.iteritems():
                record_time(phase, start, end)
                record_cpu(phase, resource_monitor.aggregate_cpu(start, end))
                record_io(phase, resource_monitor.aggregate_io(start, end))

    def _build(self, resource_monitor, on_phase, on_backend):
        # Builds involve roughly 3 steps:
        #  1) configure
        #  2) build config
        #  3) building

        self._ensure_objdir_exists()

        @contextmanager
        def do_phase(phase):
            resource_monitor.begin_phase(phase)
            yield
            resource_monitor.finish_phase(phase)

        with do_phase('configure'):
            c = self._spawn(Configure)
            c.ensure_configure()

        # Ensure the build config/backend is proper.
        with do_phase('backend_config'):
            manager = self._spawn(BackendManager)
            manager.set_backend(self.settings.build.backend)

            if on_backend:
                on_backend(manager.backend)

            manager.ensure_generate()

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
                return

            match = RE_LEAVING_DIRECTORY.match(line)
            if match:
                directory = match.group('directory')

                if not directory.startswith(self.objdir):
                    return

                relative = directory[len(self.objdir) + 1:]
                return

            # We don't log the entering/leaving directory messages because
            # they are spammy. The callback can choose to display something if
            # it really wants.
            self.log(logging.INFO, 'make', {'line': line}, '{line}')

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

        def on_action(action, **kwargs):
            if action == 'make_output':
                handle_line(kwargs['line'])
                return

            if action == 'enter_phase':
                resource_monitor.begin_phase('build_%s' % kwargs['phase'])

                if on_phase:
                    on_phase(kwargs['phase'])

                return

            if action == 'leave_phase':
                resource_monitor.finish_phase('build_%s' % kwargs['phase'])

        manager.backend.add_listener(on_action)

        with do_phase('build'):
            manager.build()

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
