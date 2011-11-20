The Build Splendid Build System
===============================

The code in this tree contains an alternate build system for Mozilla projects.

Main Features
=============

Unified Build Tool
------------------

A new file, build.py, is introduced in the main source directory. This
file serves as a gateway to common build actions, including build
configuration.

The first time you run build.py,

  $ ./build.py

The tool recognizes that you don't have an existing build config and opens a
wizard to help you create one. The config files are replacements for mozconfig
files.

You launch build.py with an action you want to perform. Common actions are
"configure," "makefiles," or "build." When you run an action, the prerequisites
are executed automatically.

The unified build tool also has nifty output formatting. By default, output is
very silent, so you only see high-level logging to stdout. Even when you run
configure, you just see "starting configure" [wait 10 seconds] "Configure
finished." Of course, you can turn on verbose mode to see everything. Each
output line contains a relative timestamp from action start so you can see how
long things are taking. There is also a forensic log mode which writes newline-
delimited JSON objects describing each entry. This allows for easier machine
consumption of logs without having to write a complicated parser.

Derecursified Makefile Generation
---------------------------------

This build system is capable of producing a fully-derecursified Makefile. It
accomplishes this by parsing existing Makefiles for variables that have
rules from rules.mk (like CPPSRCS or EXPORTS) and dynamically produces a new
Makefile with individual rules for these. See the technical overview below.

BXR - The Build Cross Reference
-------------------------------

To help see how the build system is configured without having to grok
Makefiles, BXR is introduced. BXR takes metadata from the build system and
formats it to HTML.

Run BXR through build.py:

  $ ./build.py bxr

Side-by-Side Compatibility With Existing Build System
-----------------------------------------------------

Build Splendid has been designed to be installed side-by-side with the existing
build system. It makes no backwards-incompatible changes that should impact the
existing build system. So, once it lands, developers can select which one to
use.

The only caveat is Build Splendid needs to own the object directory. So, you
can't use both build systems on the same output directory. But, you can have
both working from the same source directory.

Changes to Existing Files
-------------------------

* configure.in's updated to allow optional suppression of Makefile.in
  conversion. Build Splendid can perform this conversion itself.

FAQ
===

Is this a full build system replacement?
----------------------------------------

No. There is lots of functionality in the original build system (PGO, i10n,
packaging, etc) that is not yet implemented in this build system. However,
functionality that I think is used by 95% of people is included. So, for
most developers, this build system should suffice.

We should care about making this build system more robust because it builds
much, much faster.

Why did you kill mozconfigs?
----------------------------

Because they are annoying and error prone. I find it extremely annoying that
the documentation for all the options is on a web site. The configurable
options need to be versioned with the code so users are guaranteed to get
correct information when setting up things. And, our current validation
story is a joke. Even if it were pretty good, I'd rather do validation in
Python than in configure or makefiles.

Have any performance numbers?
-----------------------------
Yes!

Linux and Windows numbers executed on a Core i7-2600K running in 64-bit. Linux
was running in a VM, but the VM had 4GB dedicated memory.

Under Linux:

  # Empty object directory configure
  * 13.8s - $ make -f client.mk configure
  * 14.1s - $ make.py -f client.mk configure
  * 13.1s - $ build.py configure

Please note that build.py does *not* produce Makefile during configure phase.

  # PyMake performance
  * 2.8s  - PyMake parse all 1148 Makefile.in into statement list

When can this get checked in?
-----------------------------

I don't know. It is a lot of code that needs to be reviewed. And, some test
code likely needs written.

Technical Overview
==================

Most new code is located in build/buildparser and is defined as Python
modules for reusability.

The code is conceptualized in 3 components: parsing/extraction,
representation, and transformation.

In the parsing/extraction component, data from our existing build system
is read or inferred from existing files, mainly Makefiles. This component
contains all the logic for inferring how our build system works today. It
looks at a Makefile and says "it is producing a static library from input
files X and Y," "it is exporting an IDL I," "it defines some JavaScript
modules J," etc.

The parsing/extraction component converts existing data into unified and
rather generic data structures. These data structures can be thought of as
the data-centric components of the Makefiles. In other words, they are
Makefiles without targets and rules.

The third component is transformation. Transformation components take the
data representations from the previous component and transform them into
something. For example, it could take all the libraries and produce Visual
Studio projects for them. Or, you could produce a derecursified Makefile.

To visualize, data moves through the system thus:

  |------------|           |---------------|           |----------------|
  |            |           |               |           |                |
  | Extraction | -->-->--> |Representation | -->-->--> | Transformation |
  |            |           |               |           |                |
  |------------|           |---------------|           |----------------|
                                                               |
                                            |--------|         |
                                            |        |         |
                                            | Output | <---<---|
                                            |        |
                                            |--------|

Currently, the only Transformation stage implemented in the branch is Visual
Studio.

Visual Studio Generation
========================

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

Extraction in Detail
====================

As stated previously, the first step is data extraction from the existing
build system. This is worth expanding on.

Many of the Makefiles in the Mozilla source tree are data-driven and mostly
declarative. You define a variable of a certain name, say "CPPSRCS," and
an inherited makefile converts that to a target and applies a known rule
for doing something with it. In our example, it knows that every item inside
"CPPSRCS" is a C++ source file and should be compiled with the C++ compiler.

The code in buildparser/makefile.py extracts the data-side of this convention
using the PyMake API to access Makefile variables.

MozillaMakefile.get_data_objects() is a generator function which emits a set of
data.MakefileDerivedObject's which describe what the Makefile is defining. For
example, it may emit a LibraryInfo, XPIDLInfo, and TestInfo, each describing a
specific aspect of the Makefile. These items are all related in that they are
defined by the same Makefile. However, in terms of a build system, they are
mostly independent.

The code in extractor.py merely iterates over all Makefiles in the build tree
and emits a stream of these MakefileDerivedObject's.

The set of emitted representations of build system entities is aggregated in
a unified Python object, TreeInfo. This object is effectively a giant data
structure defining our build system. Of course, there are convenient APIs on
this data structure.

Transformation
==============

Once you have the build system defining as a data structure, the sky is the
limit in terms of what you can do. Here are some ideas:

* Produce Visual Studio projects
* Produce XCode projects
* Produce a derecursified Makefile
* Produce GYP files and then arrive at above
* Produce an SVG depicting dependencies between entities
* Write a custom build tool which efficiently performs work on the in-memory
  dependency graph

Effort is currently being spent on Visual Studio output because Windows
development is the most lacking of all the platforms, IMO. However,
transformations to a derecursified Makefile are very interesting and will
likely lead to significant performance wins.

In a build utopia, it would be possible to build the entire tree without having
to fork() or create a new thread (except for parallelism, which we'd obviously
want). This could be done by coding all the build steps in Python (or any
language - Python is the obvious choice since a lot of our support tools used
during the build process are written in Python today) and then performing a
function call into LLVM/Clang to do the compiling (LLVM/Clang, unlike GCC, is
designed as a library, so you can do crazy stuff like this).

Visual Studio Support
=====================

We can generate the following in Visual Studio:

* Projects from all Makefiles
* A solution incorporating all projects
* C++ static libraries
* IDL generation
* Basic dependencies

The following doesn't work yet:

* JavaScript integration
* Test integration
* .exe generation
* DLL generation
* Proper dependencies

Ramble on Data Driven Building
==============================

This experiment relies on data-driven and declarative build data. What I mean
by that is that the entities describing what is built should be declarative
and be focused on the data itself, not how to build it. This is the approach
Google takes with their GYP system. GYP uses Python-syntax files to define the
build system (see https://code.google.com/p/gyp/wiki/GypLanguageSpecification).

By doing this, you loosely couple the *what* from the *how*. This means that
instead of having one system (Make) define both (oftentimes intermixed in the
same file), you have the option of selecting the system you use to perform the
*how* (the actual building). This could certainly be Make. It could (almost as
easily) be Visual Studio.

My wording may sound foreign to you, but it is the direction we have trended
in with the build system. Look at
https://hg.mozilla.org/mozilla-central/file/1c7e1db3645b/netwerk/cookie/Makefile.in
Nearly every line in that file is a static variable assignment. At the bottom,
we have a couple of includes. Deep in the bowels of rules.mk are a bunch of
rules that say "oh, you defined XPIDLSRCS: those are IDL files. I'll need to
produce header files by running an IDL conversion script and then I should copy
those files somewhere" or "I need to compile every file in CPPSRCS with the
extra DEFINE's you added." All this complicated logic is (rightfully)
abstracted away from the Makefile and the end-developer, meaning only a handful
of people need punish themselves with the horid details of how rules.mk works.

It's a pretty good system. But it isn't perfect. The main problem is there are
a lot of one-offs throughout the Makefiles. But, it's not the length of the
tail that is bothersome, it is the unpredictability of it.

By storing declarative data in Makefiles, we leave the proverbial door open
for someone to do something unaccounted for. What happens when a new target
is added to an individual Makefile? Does our extraction tool recognize this?

For the extraction and translation tools to be reliable and less prone to
breaking, we need enforcement of coding practices. We essentially want to
make everything static (i.e. variable assignment only in Makefiles outside
of config/) to minimize the risk and variance. At the point we achieve this,
there is really no point to storing the data in Makefiles at all! As parsing
Makefiles is a fool's errand (if you know how Makefiles work, you will
recognize that "parse" and "Makefile" don't go together), we should
probably store data in something else, like YAML. It will be much, much easier
to enforce standard practices on this type of a data structure than Makefiles.
