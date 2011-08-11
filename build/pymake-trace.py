#!/usr/bin/env python

# This is an experimental script to build Microsoft Visual Studio project files
# from a PyMake trace log. It will likely explode, killing many kittens in the
# process.

import json
import sys

def parse_trace_log(path):
    modules = {}

    with open(path, 'r') as f:
        l = f.readline()
        first = json.loads(l)
        assert first[0] == 'MAKEFILE_BEGIN'

        root = first[1]['dir']
        print 'Root directory: %s' % root

        current_dir = root
        level = 0

        current_make_vars = None

        for line in f:
            o = json.loads(line)
            action, data = o

            if action == 'MAKEFILE_BEGIN':
                dir = data['dir']
                assert dir.find(root) == 0

                current_dir = dir[len(root):]
                current_make_vars = data['variables']

                print '%sNEW MAKEFILE: %s' % ( ' ' * level, current_dir )
                level += 1

            elif action == 'MAKEFILE_FINISH':
                level -= 1
                print '%sEND MAKEFILE' % ( ' ' * level )

            elif action == 'TARGET_BEGIN':
                name = data['target']
                vars = data['variables']

                if name == 'build':
                    print '%sBUILD TARGET!!!' % ' ' * level
                    if current_make_vars:
                        for k, v in current_make_vars.items():
                            print '%s%s = %s' % ( ' ' * level, k, v[2] )

                print '%sBEGIN TARGET: %s' % ( ' ' * level, name )
                level += 1

            elif action == 'TARGET_FINISH':
                name = data['target']

                level -= 1
                print '%sEND TARGET %s' % ( ' ' * level, name )

            elif action == 'COMMAND_RUN':
                command = data['cmd']

                print '%s$ %s' % ( ' ' * level, command )


def main(argv):
    if len(argv) != 1:
        raise Exception('Must define path to trace log as arugment')

    parse_trace_log(argv[0])

if __name__ == '__main__':
    main(sys.argv[1:])
