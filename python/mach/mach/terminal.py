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


class BuildTierFooter(TerminalFooter):
    # TODO grab these from build system properly.
    TIERS = ['base', 'nspr', 'js', 'platform', 'app']
    ACTIONS = ['default', 'export', 'libs', 'tools']

    def __init__(self, terminal):
        TerminalFooter.__init__(self, terminal)

        self.tier = None
        self.action = None
        self.directories = {}

    def clear(self):
        self._clear_lines(1)

    def draw(self):
        # This seems to make the printed text from jumping between column 0 and
        # 1. Not sure what the underlying cause of that is.
        print >>self.fh, self.t.move_x(0),

        print >>self.fh, self.t.bold('TIER') + ':',
        for tier in self.TIERS:
            if tier == self.tier:
                print >>self.fh, self.t.yellow(tier),
            else:
                print >>self.fh, tier,

        print >>self.fh, self.t.bold('ACTION') + ':',
        for action in self.ACTIONS:
            if action == self.action:
                print >>self.fh, self.t.yellow(action),
            else:
                print >>self.fh, action,

        in_progress = 0
        finished = 0
        total = 0
        names = set()

        for name, state in self.directories.iteritems():
            total += 1

            if state['start_time'] is None:
                pass
            elif state['start_time'] and state['finish_time'] is None:
                in_progress += 1
                names.add(name)
            elif state['finish_time']:
                finished += 1
            else:
                raise Exception('Unknown directory state: %s' % state)

        if total > 0:
            print >>self.fh, self.t.bold('DIRECTORIES') + ':',
            print >>self.fh, '%02d/%02d/%02d' % (in_progress, finished, total),

            if in_progress > 0:
                print >>self.fh, '(' + self.t.magenta(' '.join(names)) + ')',


class BuildTerminal(object):
    """The terminal displayed during builds."""
    def __init__(self, log_manager):
        self.footer = None

        terminal = log_manager.terminal

        if not terminal:
            return

        self.t = terminal
        self.footer = BuildTierFooter(terminal)

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

    def draw_directory_update(self, action, directory, state):
        if action != 'directory_finish':
            self.refresh()
            return

        elapsed = state['finish_time'] - state['start_time']

        parts = [
            '-' * 6,
            '%.2fs' % elapsed,
            '%s %s %s finished' % (self.footer.tier, self.footer.action,
                directory),
            '',
        ]

        width = self.t.width
        if width > 80:
            width = 80

        msg = ' '.join(parts)
        msg += '-' * (width - len(msg))

        self.write_line(self.t.magenta(msg))

    def update_progress(self, build=None, action=None, directory=None):
        if not self.footer or build.tier is None:
            return

        self.footer.tier = build.tier

        subtier = build.action

        if not subtier:
            subtier = 'default'

        self.footer.action = subtier
        self.footer.directories = build.directories

        if action in ('directory_start', 'directory_finish'):
            self.draw_directory_update(action, directory,
                    build.directories[directory])
            return

        # Force a redraw.
        self.refresh()
