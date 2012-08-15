# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this file,
# You can obtain one at http://mozilla.org/MPL/2.0/.

"""This file contains code for interacting with terminals.

All the terminal interaction code is consolidated so the complexity can be in
one place, away from code that is commonly looked at.
"""

import logging
import sys


class LoggingHandler(logging.Handler):
    """Custom logging handler that works with terminal window dressing.

    This is alternative terminal logging handler which contains smarts for
    emitting terminal control characters properly. Currently, it has generic
    support for "footer" elements at the bottom of the screen. Functionality
    can be added when needed.
    """
    def __init__(self):
        logging.Handler.__init__(self)

        self.fh = sys.stdout
        self.footer = None

    def flush(self):
        self.acquire()

        try:
            self.fh.flush()
        finally:
            self.release()

    def emit(self, record):
        msg = self.format(record)

        if self.footer:
            self.footer.clear()

        self.fh.write(msg)
        self.fh.write('\n')

        if self.footer:
            self.footer.draw()

        # If we don't flush, the footer may not get drawn.
        self.flush()


class TerminalFooter(object):
    """Represents something drawn on the bottom of a terminal."""
    def __init__(self, terminal):
        self.t = terminal
        self.fh = sys.stdout

    def _clear_lines(self, n):
        for i in xrange(n):
            print >>self.fh, self.t.move_x(0), self.t.clear_eol(),
            print >>self.fh, self.t.move_up(),

        print >>self.fh, self.t.move_down(), self.t.move_x(0),

    def clear(self):
        raise Exception('clear() must be implemented.')

    def draw(self):
        raise Exception('draw() must be implemented.')


class BuildPhaseFooter(TerminalFooter):
    def __init__(self, terminal):
        TerminalFooter.__init__(self, terminal)

        self.phases = []
        self.phase = None

    def clear(self):
        self._clear_lines(1)

    def draw(self):
        # This seems to make the printed text from jumping between column 0 and
        # 1. Not sure what the underlying cause of that is.
        print >>self.fh, self.t.move_x(0),

        print >>self.fh, self.t.bold('PHASE') + ':',
        for phase in self.phases:
            if phase == self.phase:
                print >>self.fh, self.t.yellow(phase),
            else:
                print >>self.fh, phase,


class BuildTerminal(object):
    """The terminal displayed during builds."""
    def __init__(self, log_manager):
        self.footer = None

        terminal = log_manager.terminal

        if not terminal:
            return

        self.t = terminal
        self.footer = BuildPhaseFooter(terminal)

        handler = LoggingHandler()
        handler.setFormatter(log_manager.terminal_formatter)
        handler.footer = self.footer

        log_manager.replace_terminal_handler(handler)

    def __del__(self):
        if self.footer:
            self.footer.clear()

    def write_line(self, line):
        if self.footer:
            self.footer.clear()

        print line

        if self.footer:
            self.footer.draw()

    def refresh(self):
        if not self.footer:
            return

        self.footer.clear()
        self.footer.draw()

    def update_phase(self, phase=None):
        if not self.footer or phase is None:
            return

        if phase == self.footer.phase:
            return

        self.footer.phase = phase

        # Force a redraw.
        self.refresh()

    def register_phases(self, phases):
        if not self.footer:
            return

        self.footer.phases = phases
