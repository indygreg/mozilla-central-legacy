This is a branch adding experimental Visual Studio project generation to
mozilla-central.

The crux of the code is in build/buildparser.py and build/generate-msvc.py.

This documentation may be spotty at times. I apologize.

Things are in a very hacky state and are very fragile. It is a work in
progress. You have beer warned.

To build Visual Studio projects and a solution, assuming you have a clean
checkout, first launch your Windows compilation environment by starting
start-msvc9.bat from mozilla-build. Then:

    ./build/pymake/make.py -f client.mk
    python ./build/generate-msvc.py -p /path/to/python /absolute/path/to/obj-dir

Yes, you need to build the tree first. I'm working on it!

Basically, you point generate-msvc.py at your object directory (which contains
the generated Makefiles) and it scans all the Makefiles, extracts metadata
(using the PyMake API) and uses this to produce Visual Studio files. The
generated files are in obj-dir/msvc/. You probably want to open mozilla.sln.

By default, generate-msvc.py outputs Visual Studio 2008 files. Theoretically
it supports 2005 and 2010 file formats. But, I haven't fully tested with these
yet. The formats are mostly compatible, I just need to do the leg work. So,
stick with MSVC 2008, please.

How it Works
============

As stated previously, project generation works by extracting metadata from
Makefiles. This is worth expanding on. Many of the Makefiles in the source
tree are similar by convention: they contain variables like "CPPSRCS" and
"XPIDLSRCS" that identify sets of files to operate on. Makefile magic in
config/rules.mk expands these variables to rules that perform the build steps.
For the Makefiles that follow this convention, we need to emulate behavior of
rules.mk in Visual Studio projects. This is easier said than done, as rules.mk
is quite complex. But, it should be possible.

MSVC generation effectively works in two passes:

  1) Extract metadata from Makefiles
  2) Convert metadata into Visual Studio projects

Theoretically, step #2 could be any build system target. I have just focused
on MSVC for this branch.

Currently, the extraction process is limited to Makefiles defining C++
libraries and modules. For all other Makefiles, it falls back to just saying
"hey, this thing exists."

The process of converting the metadata into Visual Studio projects is
cumbersome. The VisualStudioBuilder class encapsulates this logic. The
build_project method is what does all the magic. It takes a bunch of
arguments and tries to do the right thing. For C++ projects, it is able
to convert the compiler arguments to Visual Studio project native options.
The coverage is far from complete, however. Currently, it just prints on
unknown flags and these are dropped. With enough time, we should get 100%
coverage.

What Works
==========

Basic Visual Studio project generation works. Files from the directories are
included in the projects. It also produces a solution which includes all the
projects. When you open a file for editing, IntelliSense seems to work!

C++ library projects are created as such. Using a vanilla .mozconfig, it will
recognize all the arguments for .cpp compilation and convert these to project
options.

What Doesn't Work
=================

A lot.

Things don't compile inside Visual Studio. IDL's are completely broken. Some
C++ files may compile, but more often than not they don't. If you want to try
to build C++ files, you'll need to remove IDL files from the project.

There are no defined dependencies inside the solution, so even if things
did build, the order would be all wrong.

JavaScript files aren't included in projects.

Shared libraries aren't defined in projects yet.

There are countless known issues and limitations. We'll get there...

Ramble on Build Metadata
========================

I want to emphasize the importance of having a Makefile "style" convention.
What I mean by this is having all the Makefiles have the same typical pattern
of declaring the same variables. The metadata extraction process used here
relies on this. If (by some miracle) I get this branch to the point where I
can fully build in Visual Studio by extracting metadata from Makefiles, all
it would take is one change to a Makefile somewhere which breaks the
convention and things would fall down.

One solution to this is auditing. I would /love/ for us to have some kind of
build system auditing tool (preferably executed as part of the test suite so
checkins that fail audit are treated as a failed build and should be backed
out). This auditing tool would ensure that all Makefiles follow our defined
sets of conventions. For example, we could easily check that:

* All .h, .cpp, .idl, etc files in a directory are defined in Makefiles (this
  will help prevent orphans)
* All Makefiles producing libraries define all required variables
* No one-off styles exist in Makefiles

Once the auditing is in place and the tree complies, the job of extracting
metadata from the Makefiles is much simpler since the number of patterns that
need detected and dealt with should be much smaller than it is today.

Once we have confidence in an extractor that works reliably, it should be
possible to do crazy things like assembling all this metadata, writing it in
a sane, declarative format (YAML?), then deleting the source Makefiles. We can
then transform this simpler declarative format into files that our favorite
build system can read (GNU Make, MSVC, XCode, etc). If we wanted to be even
more clever, we could take the dependency information from this metadata
(because we captured that during the transition, of course), build a directed
graph, and make our own intelligent build tool that is never stalled because
its dependency model only applies to directories. Or, maybe we could switch to
something like GYP (https://code.google.com/p/gyp/), which I believe does a
lot of what I'm describing. It's all possible when the declarative metadata
is liberated from Makefiles.