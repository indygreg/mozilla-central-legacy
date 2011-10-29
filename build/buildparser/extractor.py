# ***** BEGIN LICENSE BLOCK *****
# Version: MPL 1.1/GPL 2.0/LGPL 2.1
#
# The contents of this file are subject to the Mozilla Public License Version
# 1.1 (the "License"); you may not use this file except in compliance with
# the License. You may obtain a copy of the License at
# http://www.mozilla.org/MPL/
#
# Software distributed under the License is distributed on an "AS IS" basis,
# WITHOUT WARRANTY OF ANY KIND, either express or implied. See the License
# for the specific language governing rights and limitations under the
# License.
#
# The Original Code is Mozilla build system.
#
# The Initial Developer of the Original Code is Mozilla Foundation.
# Portions created by the Initial Developer are Copyright (C) 2011
# the Initial Developer. All Rights Reserved.
#
# Contributor(s):
#  Gregory Szorc <gps@mozilla.com>
#
# Alternatively, the contents of this file may be used under the terms of
# either the GNU General Public License Version 2 or later (the "GPL"), or
# the GNU Lesser General Public License Version 2.1 or later (the "LGPL"),
# in which case the provisions of the GPL or the LGPL are applicable instead
# of those above. If you wish to allow use of your version of this file only
# under the terms of either the GPL or the LGPL, and not to allow others to
# use your version of this file under the terms of the MPL, indicate your
# decision by deleting the provisiwons above and replace them with the notice
# and other provisions required by the GPL or the LGPL. If you do not delete
# the provisions above, a recipient may use your version of this file under
# the terms of any one of the MPL, the GPL or the LGPL.
#
# ***** END LICENSE BLOCK *****

# This file contains classes and methods used to extract metadata from the
# Mozilla build system.
#
# TODO the Visual Studio foo needs to be purged and loosely coupled

from buildparser.makefile import MozillaMakefile
from buildparser.visualstudio import VisualStudioBuilder, visual_studio_product_to_internal_version
from os import mkdir
from os.path import basename, isabs, exists, join
from pymake.data import Makefile
from time import localtime, time, strftime
from uuid import uuid1
from xml.etree.ElementTree import Element

import xml.etree.ElementTree

class BuildParser(object):
    '''Extracts metadata from the build system.'''

    def __init__(self, objdir):
        if not isabs(objdir):
            raise Exception('Path not absolute: %s' % objdir)

        self.dir = objdir

        path = join(objdir, 'Makefile')
        if not exists(path):
            raise Exception('Makefile does not exist: %s' % path)

        self.topmakefile = MozillaMakefile(path)
        self.topsourcedir = self.topmakefile.get_top_source_dir()

    def get_tiers(self):
        return self.topmakefile.get_variable_split('TIERS')

    def get_platform_dirs(self):
        return self.topmakefile.get_variable_split('tier_platform_dirs')

    def get_base_dirs(self):
        '''Obtain a list of the configured base directories'''
        return self.topmakefile.get_variable_split('tier_base_dirs')

    def get_dir_makefile(self, path):
        full = join(self.dir, path)
        file = join(full, 'Makefile')

        if not exists(file):
            raise Exception('path does not exist: %s' % file)

        return (MozillaMakefile(file), full, file)

    def get_top_source_directory(self):
        return self.topmakefile.get_variable_string('topsrcdir')

    def get_module_data(self, path):
        makefile, full, file = self.get_dir_makefile(path)
        assert(makefile.is_module())

        d = {
            'libraries': [],
            'unhandled': [],
        }

        dirs = makefile.get_dirs()
        dirs.sort()
        for dir in dirs:
            submake, subfull, subfile = ( None, None, None )

            subpath = join(path, dir)
            try:
                submake, subfull, subfile = self.get_dir_makefile(subpath)
            except:
                print 'Makefile for referenced directory does not exist: %s' % subpath
                continue

            library = submake.get_library()
            if library is not None:
                d['libraries'].append(submake.get_library_info())
                continue

            d['unhandled'].append(subpath)

        return d

    def build_visual_studio_files(self, python=None, version='2008', pymake=None):
        '''Build Visual Studio files for the tree

        Calling this will result in a bunch of files being written to
        objdir/msvc.

        Currently, the written files are far from feature complete. For
        example, we don't yet know how to handle all the Makefiles in the
        tree.

        Arguments:

          version - Visual Studio product version to write files for. One of
                    {2005, 2008, 2010, or 2011}. Specified as a string.

          pymake - Path to pymake command line program. Defaults to
                   topsrcdir/pymake/make.py.
          python - Path to python executable that is runnable from Visual
                   Studio. Currently, this must be specified. In the future, we
                   might auto-discover it.
        '''
        if pymake is None:
            pymake = join(self.get_top_source_directory(), 'build', 'pymake', 'make.py')

        if python is None:
            # TODO try to find by environment
            raise Exception('Could not find Python')

        builder = VisualStudioBuilder()
        outdir = join(self.dir, 'msvc')

        if not exists(outdir):
            mkdir(outdir)

        # TODO fix directories causing us hurt
        ignore_dirs = [
            'js/src/xpconnect', # hangs
            'js/xpconnect',     # somehow forks and calls itself recursively
            'modules/libbz2',   # somehow forks and calls itself recursively
            'security/manager', # hangs
        ]

        projects = {}

        # maps files to be copied in the top project, which always gets built
        top_copy = {
            '$(MOZ_OBJ_DIR)\\mozilla-config.h': '$(MOZ_OBJ_DIR)\\dist\\include\\mozilla-config.h',
        }

        strversion = visual_studio_product_to_internal_version(version, True)

        def handle_project(project, id, name, dependencies=[]):
            filename = '%s.vcproj' % name
            projfile = join(outdir, filename)

            with open(projfile, 'w') as fh:
                fh.write(project)

            entry = {
                'id':           id,
                'name':         name,
                'filename':     filename,
                'dependencies': dependencies,
            }

            projects[id] = entry

        # Handle NSPR as a one-off, as it doesn't conform.
        def process_nspr():
            def handle_nspr_makefile(m):
                local_children = []

                # recurse immediately
                for dir in m.get_dirs():
                    m2 = self.get_dir_makefile(join(m.dir, dir))[0]
                    child_project = handle_nspr_makefile(m2)
                    if child_project:
                        local_children.append(child_project)

                # now handle the NSPR logic
                headers = []
                srcdir = m.get_variable_string('srcdir')
                for header in m.get_variable_split('HEADERS'):
                    if header.find(srcdir) == 0:
                        headers.append(header[len(srcdir)+1:])
                    else:
                        headers.append(header)

                sources = m.get_variable_split('CSRCS')

                # RELEASE_HEADERS get copied to output directory
                release_headers = m.get_variable_split('RELEASE_HEADERS')

                header_dist_dir = m.get_variable_string('dist_includedir')

                # bad code alert!
                if m.reldir == 'pr\\include\\obsolete':
                    header_dist_dir = join(header_dist_dir, 'obsolete')
                elif m.reldir == 'pr\\include\\private':
                    header_dist_dir = join(header_dist_dir, 'private')

                pre_copy = {}
                for header in release_headers:
                    dest = join(header_dist_dir, basename(header)).replace('/', '\\')
                    pre_copy[header.replace('/', '\\')] = dest

                name = 'nspr'
                parent = True

                type = 'custom'
                if m.reldir:
                    type = 'static'
                    name = 'nspr_%s' % m.reldir.replace('\\', '_')
                    parent = False

                if not len(sources):
                    type = 'utility'

                # ignore nspr/config b/c we don't need it (yet)
                if name == 'nspr_config':
                    return None
                elif name == 'nspr_pr_src':
                    # for some reason this Makefile pulls in sources compiled
                    # elsewhere
                    sources = []

                flags = m.get_variable_split('CFLAGS')
                mkdir = []

                # plvrsion.c looks for a header in the output directory
                if 'plvrsion.c' in sources:
                    flags.append('-I%s' % m.get_variable_string('OBJDIR'))

                shared_library = None
                library_dependencies = []

                # For shared libraries, the link command in the simple case is:
                # $(LINK_DLL) -MAP $(DLLBASE) $(DLL_LIBS) $(EXTRA_LIBS) $(OBJS) $(RES)
                # This comes from nsprpub's rules.mk when building the
                # $(SHARED_LIBRARY) target.
                if m.has_variable('LIBRARY_NAME'):
                    type = 'shared'
                    shared_library = '$(IntDir)\%s%s.dll' % ( m.get_variable_string('LIBRARY_NAME'),
                                                              m.get_variable_string('LIBRARY_VERSION'))

                    library_dependencies.extend(m.get_variable_split('EXTRA_LIBS'))

                    #for v in ('LINK_DLL', 'DLLBASE', 'DLL_LIBS', 'RES'):
                    #    print '%s: %s' % ( v, m.get_variable_split(v) )

                xml, id, project_name = builder.build_project(
                    version=version,
                    name=name,
                    dir=m.dir,
                    source_dir=m.get_variable_string('srcdir'),
                    reldir=join('nsprpub', m.reldir),
                    type=type,
                    headers=headers,
                    c_sources=sources,
                    cxxflags=flags,
                    mkdir=mkdir,
                    pre_copy=pre_copy,

                    shared_library=shared_library,
                    link_dependencies=library_dependencies,
                    linker_link_library_dependency_inputs=True,
                    linker_generate_manifest=False, # TODO support this
                )

                dependencies = local_children

                # Ensure include files are copied before compilation.
                if project_name.find('src') != -1:
                    dependencies.append('nspr_pr_include')

                if project_name.find('nspr_lib') == 0:
                    dependencies.append('nspr_pr_src')

                dependencies.append('nspr_bld_header')

                print 'Writing NSPR project for %s' % project_name
                handle_project(xml, id, project_name, dependencies)

                return project_name

            m = self.get_dir_makefile('nsprpub')[0]
            handle_nspr_makefile(m)

            # NSPR has some special build events to copy certain files, etc.
            # We emulate this using a special project which does all this as
            # pre-build events. In the ideal world, these actions would be as
            # custom builders on files in the project. That's a little effort,
            # so we go the easy route for now.
            #
            # NSPR produces a set of auto-generated .h files. We create these
            # files as build events.
            # TODO we could probably put these commands on the projects they
            # are closest to.
            now = time()

            # Y U not use GMT???
            build_string = strftime('%Y-%m-%d %H:%M:%S', localtime(now))
            t = int(int(now) * 1000000 + (now - int(now)) * 1000000)
            build_time = '%si64' % t

            out_paths = {
                'pr\\src\\_pr_bld.h': 'nspr4.dll',
                'lib\\libc\\src\\_pl_bld.h': 'plc4.dll',
                'lib\\ds\\_pl_bld.h': 'plds4.dll',
            }

            commands = []
            for path, name in out_paths.iteritems():
                out_file = '$(MOZ_OBJ_DIR)\\nsprpub\\%s' % path
                commands.append('echo #define _BUILD_STRING "%s" > %s' % ( build_string, out_file ))
                commands.append('echo #define _BUILD_TIME %s >> %s' % ( build_time, out_file ))
                commands.append('echo #define _PRODUCTION "%s" >> %s' % ( name, out_file ))

            copies = {}

            # NSPR also has a set of per-platform .cfg files. We copy these to
            # the output directory.
            md_makefile = self.get_dir_makefile('nsprpub\\pr\\include\\md')[0]
            for config in md_makefile.get_variable_split('CONFIGS'):
                source = config.replace('/', '\\')
                dest = '$(MOZ_OBJ_DIR)\\dist\\include\\nspr\\md\\%s' % basename(config)
                copies[source] = dest

            # NSPR takes one of these config files and renames it to prcpucfg.h
            source = '$(MOZ_SOURCE_DIR)\\nsprpub\\pr\\include\\md\\%s' % m.get_variable_string('MDCPUCFG_H')
            copies[source] = '$(MOZ_OBJ_DIR)\\dist\\include\\nspr\\prcpucfg.h'

            xml, id, project_name = builder.build_project(
                version=version,
                name='nspr_bld_header',
                type='utility',
                dir=m.dir,
                pre_commands=commands,
                pre_copy=copies,
            )
            handle_project(xml, id, project_name, ['top'])

        process_nspr()

        # collect the directories we need to scan
        process_dirs = self.get_platform_dirs()
        process_dirs.extend(self.get_base_dirs())
        process_dirs.sort()

        for dir in process_dirs:
            if dir in ignore_dirs:
                continue

            m = None
            try:
                m = self.get_dir_makefile(dir)[0]
            except:
                print 'Makefile does not exist: %s' % dir
                continue

            if m.is_module():
                module = m.get_module()

                print 'Processing module "%s" in %s' % ( module, dir )

                info = self.get_module_data(dir)
                names = []
                for library in info['libraries']:
                    proj, id, name = builder.build_project_for_library(
                        library, module, version=version
                    )

                    handle_project(proj, id, name)
                    names.append(name)

                    for idl in library['xpidlsrcs']:
                        source = join('$(MOZ_SOURCE_DIR)', library['reldir'], idl)
                        top_copy[source] = join('$(MOZ_OBJ_DIR)', 'dist', 'idl', idl)

                if len(names):
                    print 'Wrote projects for libraries: %s' % ' '.join(names)

                for path in info['unhandled']:
                    print 'Writing generic project for %s' % path
                    m2 = self.get_dir_makefile(path)[0]

                    proj, id, name = builder.build_project_for_generic(
                        m2, version=version
                    )
                    handle_project(proj, id, name)

            else:
                # fall back to generic case
                print 'Writing generic project for %s' % dir
                proj, id, name = builder.build_project_for_generic(
                    m, version=version
                )
                handle_project(proj, id, name)

        # create parent project that does initialization
        # TODO we could probably do this more intelligently

        proj, id, name = builder.build_project(
            version=version,
            name='top',
            type='utility',
            dir=self.topsourcedir,
            source_dir=self.topsourcedir,
            mkdir=[
                '$(MOZ_OBJ_DIR)\\dist\\bin',
                '$(MOZ_OBJ_DIR)\\dist\\idl',
                '$(MOZ_OBJ_DIR)\\dist\\include\\nspr\\md',
                '$(MOZ_OBJ_DIR)\\dist\\include\\nspr\\obsolete',
                '$(MOZ_OBJ_DIR)\\dist\\include\\nspr\\private',
                '$(MOZ_OBJ_DIR)\\dist\\lib',
            ],
            pre_copy=top_copy,
        )
        handle_project(proj, id, name)

        # calculate dependencies
        project_name_id_map = {}
        project_dependencies = {}
        for project in projects.itervalues():
            project_name_id_map[project['name']] = project['id']

        for project in projects.itervalues():
            depends = []
            for name in project['dependencies']:
                depends.append(project_name_id_map[name])

            if len(depends):
                project_dependencies[project['id']] = depends

        # now produce the Solution file
        slnpath = join(outdir, 'mozilla.sln')
        configid = str(uuid1())
        with open(slnpath, 'w') as fh:
            # Visual Studio seems to require this header
            print >>fh, 'Microsoft Visual Studio Solution File, Format Version %s' % strversion

            # write out entries for each project
            for project in projects.itervalues():
                print >>fh, 'Project("{%s}") = "%s", "%s", "{%s}"' % (
                    configid, project['name'], project['filename'], project['id']
                )

                if project['id'] in project_dependencies:
                    print >>fh, '\tProjectSection(ProjectDependencies) = postProject'
                    for id in project_dependencies[project['id']]:
                        print >>fh, '\t\t{%s} = {%s}' % ( id, id )
                    print >>fh, '\tEndProjectSection'

                print >>fh, 'EndProject'

            # the global section defines configurations
            print >>fh, 'Global'
            print >>fh, '\tGlobalSection(SolutionConfigurationPlatforms) = preSolution'
            print >>fh, '\t\tBuild|Win32 = Build|Win32'
            print >>fh, '\tEndGlobalSection'
            print >>fh, '\tGlobalSection(ProjectConfiguration) = postSolution'
            for project in projects.itervalues():
                print >>fh, '\t\t{%s}.Build.ActiveCfg = Build|Win32' % project['id']
                print >>fh, '\t\t{%s}.Build.Build.0 = Build|Win32' % project['id']
            print >>fh, '\tEndGlobalSection'
            print >>fh, 'EndGlobal'

        # solution properties file defines a bunch of constants
        props = Element('VisualStudioPropertySheet', ProjectType='Visual C++',
            Version='8.00',
            Name='mozilla-build',
        )

        props.append(Element('UserMacro', Name='PYTHON', Value=python))
        props.append(Element('UserMacro', Name='PYMAKE', Value='$(PYTHON) %s' % pymake))

        props.append(Element('UserMacro', Name='MOZ_SOURCE_DIR', Value=self.topsourcedir.replace('/', '\\')))
        props.append(Element('UserMacro', Name='MOZ_OBJ_DIR', Value=self.dir.replace('/', '\\')))

        # IDL generator
        props.append(Element('UserMacro', Name='IDL_HEADER', Value='$(PYTHON) %s --cachedir=%s' % (
            '$(MOZ_SOURCE_DIR)\\xpcom\\idl-parser\\header.py',
            '$(MOZ_SOURCE_DIR)\\xpcom\\idl-parser'
        )))

        python_paths = [
            '$(MOZ_SOURCE_DIR)\\other-licenses\\ply',
            '$(MOZ_SOURCE_DIR)\\xpcom\\idl-parser',
        ]

        props.append(Element('UserMacro',
            Name='PYTHONPATH',
            Value=';'.join(python_paths),
            PerformEnvironmentSet='true'
        ))

        propspath = join(outdir, 'mozilla.vsprops')
        with open(propspath, 'w') as fh:
            fh.write(xml.etree.ElementTree.tostring(props, encoding='utf-8'))