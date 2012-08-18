# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this file,
# You can obtain one at http://mozilla.org/MPL/2.0/.

# This file contains miscellaneous utility functions that don't belong anywhere
# in particular.

import hashlib
import os
import multiprocessing
import psutil
import time

from collections import OrderedDict
from collections import namedtuple
from StringIO import StringIO


def hash_file(path):
    """Hashes a file specified by the path given and returns the hex digest."""

    # If the hashing function changes, this may invalidate lots of cached data.
    # Don't change it lightly.
    h = hashlib.sha1()

    with open(path, 'rb') as fh:
        while True:
            data = fh.read(8192)

            if not len(data):
                break

            h.update(data)

    return h.hexdigest()


class FileAvoidWrite(StringIO):
    """file-like object that buffers its output and only writes it to disk
    if the new contents are different from what the file may already contain.

    This was shamelessly stolen from ConfigStatus.py.
    """
    def __init__(self, filename):
        self.filename = filename
        StringIO.__init__(self)

    def close(self):
        buf = self.getvalue()
        StringIO.close(self)

        try:
            fh = open(self.filename, 'rU')
        except IOError:
            pass
        else:
            try:
                if fh.read() == buf:
                    return
            except IOError:
                pass
            finally:
                fh.close()

        parent_directory = os.path.dirname(self.filename)
        if not os.path.exists(parent_directory):
            os.makedirs(parent_directory)

        with open(self.filename, 'w') as fh:
            fh.write(buf)

    def __enter__(self):
        return self

    def __exit__(self, type, value, traceback):
        self.close()

SystemResourceUsage = namedtuple('SystemResourceUsage',
    ['start', 'end', 'cpu', 'io', 'virt', 'swap'])

class SystemResourceMonitor(object):
    """Measures system resources.

    Each instance measures system resources from the time it is started
    until it is finished. It does this on a separate process so it doesn't
    impact execution of the rest of the running process.

    Each instance is a one-shot instance. It cannot be used to record multiple
    durations.

    Aside from basic data gathering, the class supports basic analysis
    capabilities. You can query for data between ranges. You can also tell it
    when certain events occur and later grab data relevant to those events.

    In its current implementation, data is not available until metrics
    gathering has stopped. This may change in future iterations.
    """

    # The interprocess communication is complicated enough to warrant
    # explanation. To work around the Python GIL, we launch a separate
    # background process whose only job is to collect metrics. As this process
    # collects data, it stuffs it on a unidirectional pipe. On the other end,
    # we reconstruct the data and make it available to whoever instantiated
    # a class instance.

    def __init__(self):
        self.start_time = None
        self.end_time = None

        self.events = []
        self.phases = OrderedDict()

        self._active_phases = {}

        cpu = psutil.cpu_percent(0.0, True)
        io = psutil.disk_io_counters()
        virt = psutil.virtual_memory()
        swap = psutil.swap_memory()

        self._cpu_len = len(cpu)
        self._io_type = type(io)
        self._io_len = len(io)
        self._virt_type = type(virt)
        self._virt_len = len(virt)
        self._swap_type = type(swap)
        self._swap_len = len(swap)

        self._running = False
        self._stopped = False
        self._run_lock = multiprocessing.Lock()
        self._rx_pipe, self._tx_pipe = multiprocessing.Pipe(False)

        self._process = multiprocessing.Process(None,
            SystemResourceMonitor._collect,
            args=(self._run_lock, self._tx_pipe))

    def __del__(self):
        if self._running:
            self._run_lock.release()
            self._process.join()

    # Methods to control monitoring.

    def start(self):
        """Start measuring system-wide CPU resource utilization.

        You should only call this once per instance.
        """
        self._run_lock.acquire()
        self._running = True
        self._process.start()

    def stop(self):
        """Stop measuring system-wide CPU resource utilization.

        You should call this if and only if you have called start(). You should
        always pair a stop() with a start().

        Currently, data is not available until you call stop().
        """
        assert self._running
        assert not self._stopped

        self._run_lock.release()
        self._running = False
        self._stopped = True

        self.cpu = []
        self.io = []
        self.virt = []
        self.swap = []
        self.time = []

        done = False

        while self._rx_pipe.poll(1):
            k, entry = self._rx_pipe.recv()

            if k == 'time':
                self.time.append(entry)
            elif k == 'io':
                self.io.append(self._io_type(*entry))
            elif k == 'virt':
                self.virt.append(self._virt_type(*entry))
            elif k == 'swap':
                self.swap.append(self._swap_type(*entry))
            elif k == 'cpu':
                self.cpu.append(entry)
            elif k == 'done':
                done = True
            else:
                raise Exception('Unknown entry type: %s' % k)

        self._process.join()
        assert done

        # It's possible for the child process to be terminated in the middle of
        # a run. If this happens, we may not have agreement between the lengths
        # of all the data sets.
        lengths = [len(x) for x in [self.cpu, self.io, self.virt, self.swap,
            self.time]]

        if min(lengths) != max(lengths):
            l = min(lengths)
            self.cpu = self.cpu[0:l]
            self.io = self.io[0:l]
            self.virt = self.io[0:l]
            self.swap = self.swap[0:l]
            self.time = self.time[0:l]

        self.start_time = self.time[0]
        self.end_time = self.time[-1]

    # Methods to record events alongside the monitored data.

    def record_event(self, name):
        """Record an event as occuring now.

        Events are actions that occur at a specific point in time. If you are
        looking for an action that has a duration, see the phase API below.
        """
        self.events.append((time.time(), name))

    # TODO it would be handy to expose a context manager for phases.

    def begin_phase(self, name):
        """Record the start of a phase.

        Phases are actions that have a duration. Multiple phases can be active
        simultaneously. Phases can be closed in any order.

        Keep in mind that if phases occur in parallel, it will become difficult
        to isolate resource utilization specific to individual phases.
        """
        assert name not in self._active_phases

        self._active_phases[name] = time.time()

    def finish_phase(self, name):
        """Record the end of a phase."""

        assert name in self._active_phases

        phase = (self._active_phases[name], time.time())
        self.phases[name] = phase
        del self._active_phases[name]

        return phase[1] - phase[0]

    # Methods to query data.

    def range_usage(self, start=None, end=None):
        """Obtain the usage data falling within the given time range.

        This is a generator of SystemResourceUsage.

        If no time range bounds are given, all data is returned.
        """
        if start is None:
            start = self.time[0]

        if end is None:
            end = self.time[-1]

        last = self.time[0]

        for i, entry_time in enumerate(self.time):
            if entry_time < start:
                continue

            if entry_time > end:
                break

            yield SystemResourceUsage(last, entry_time, self.cpu[i], self.io[i],
                self.virt[i], self.swap[i])

            last = entry_time

    def phase_usage(self, phase):
        """Obtain usage data for a specific phase.

        This is a generator of SystemResourceUsage.
        """
        assert self._stopped

        time_start, time_end = self.phases[phase]

        return self.range_usage(time_start, time_end)

    def aggregate_cpu(self, start=None, end=None, per_cpu=True):
        """Obtain the aggregate CPU usage for a range.

        Returns a list of floats representing average CPU usage percentage per
        core if per_cpu is True (the default). If per_cpu is False, return a
        single percentage value.
        """
        cpu = [[] for i in range(0, self._cpu_len)]

        for usage in self.range_usage(start, end):
            for i, v in enumerate(usage.cpu):
                cpu[i].append(v)

        samples = len(cpu[0])

        if not samples:
            return None

        if per_cpu:
            return [sum(x) / samples for x in cpu]

        cores = [sum(x) for x in cpu]

        return sum(cores) / len(cpu) / samples

    def aggregate_io(self, start=None, end=None):
        """Obtain aggregate I/O counters for a range."""

        io = [0 for i in range(self._io_len)]

        for usage in self.range_usage(start, end):
            for i, v in enumerate(usage.io):
                io[i] += v

        return self._io_type(*io)

    # Internal stuff.

    @staticmethod
    def _collect(lock, pipe):
        """Collects system metrics.

        This is the main function for the background process. It collects
        data then forwards it on a unidirectional pipe until a lock can be
        acquired (which says it is time to exit).
        """

        data = []

        try:
            io_last = psutil.disk_io_counters()

            while not lock.acquire(False):
                io = psutil.disk_io_counters()

                # TODO Does this wrap? At 32 bits? At 64 bits?
                # TODO Consider patching "delta" API to upstream.
                io_diff = [v - io_last[i] for i, v in enumerate(io)]
                io_last = io

                # TODO times are a little weird because the CPU metric waits
                # a second before returning. We should fix this so it doesn't
                # lie.
                data.append(('time', time.time()))

                # psutil returns namedtuple instances. These can't be pickled
                # by default. So, we just send over the values are rebuild a
                # namedtuple on the other side.
                data.append(('io', io_diff))
                data.append(('virt', list(psutil.virtual_memory())))
                data.append(('swap', list(psutil.swap_memory())))
                data.append(('cpu', psutil.cpu_percent(0.5, True)))
        finally:
            for entry in data:
                pipe.send(entry)

            pipe.send(('done', None))
            pipe.close()
