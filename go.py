#
# go.py - Waf tool for compiling Go source code.
#
# Written by Michael Budde <mbudde@gmail.com> (2009).
#

import os, os.path, re
from sys import exit

import Task, Utils, Options
from Configure import conftest, conf
from TaskGen import taskgen, feature, before, after, extension
from Logs import debug, error

EXT_GO = ['.go']


class GoParser(object):

    def __init__(self, tg):
        self.tg = tg

        self.re_package = re.compile(r"package\s+(?P<pkg>\S+)\s+", re.U | re.M)
        self.re_import = re.compile(
            r"""
            import \s+
            ( ( \. | \S+ ) \s+ )?
            [`"](?P<inc>[^`"\n]*)[`"] \s+
            """,
            re.U | re.M | re.X)
        self.re_import_paren = re.compile(
            r"""
            import \s+ \( ([^\)]*) \)
            """,
            re.U | re.M | re.X | re.S )
        self.re_import_in_paren = re.compile(
            r"""
            ( ( \. | [^`"]+ ) \s+ )?
            [`"](?P<inc>[^`"\n]*)[`"] \s*
            ;?
            """,
            re.U | re.M | re.X )

    def start(self, nodes):
        self.packages = {}
        self.deps = {}
        self.parse_queue = nodes
        while self.parse_queue:
            n = self.parse_queue.pop(0)
            self._iter(n)
        for pkg, deps in self.deps.iteritems():
            self.deps[pkg] = [x for x in deps if x in self.packages]

    def _iter(self, node):
        path = node.abspath(self.tg.env)
        try:
            code = Utils.cmd_output(' '.join([self.tg.env['GOFMT'], '-comments=false', path]))
        except ValueError, e:
            error(str(e))
            exit(1)

        package = self._find_package(code)
        if package not in self.packages:
            self.packages[package] = []
        self.packages[package].append(node)

        imports = self._find_imports(code)
        imports = [os.path.basename(i) for i in imports]
        if package not in self.deps:
            self.deps[package] = []
        self.deps[package] += imports

    def _find_package(self, code):
        return self.re_package.search(code).group('pkg')

    def _find_imports(self, code):
        imports = []
        iter = self.re_import.finditer(code)
        for m in iter:
            imports.append(m.group('inc'))
        iter = self.re_import_paren.finditer(code)
        for m in iter:
            iter2 = self.re_import_in_paren.finditer(m.group(1))
            for m2 in iter2:
                imports.append(m2.group('inc'))
        return imports


class GoPackage(object):

    def __init__(self, name, nodes=[], uselib_local=[]):
        self.name = name
        self.target = name
        self.inputs = nodes 
        self.build_task = None
        self.link_task = None
        self.pack_task = None
        self.uselib = []
        self.uselib_local = uselib_local

###############################
# Options
###############################

def set_options(opt):
    opt.add_option('--gofmt', action='store_const', const='format', default=False,
                   help='run source code through gofmt before compiling')
    opt.add_option('--gofmt-list', action='store_const', const='list', dest='gofmt',
                   help='list files whose formatting differs from gofmt\'s')

###############################
# Configuring
###############################

def check_and_set_var(var, env, values=None):
    """ Check if env[var] is set, if not try to get the var from os environment.
    If that fails return False, else return True. Optionally check if var's
    value is in values, if not return False.
    """
    if var in env:
        if values and env[var] in values:
            return True
    val = os.getenv(var)
    if val:
        if not values or val in values:
            env[var] = val
            return True
    return False

@conftest
def go_vars(conf):
    v = conf.env
    fail = False
    ok = check_and_set_var('GOROOT', v)
    if not ok:
        error('GOROOT is set not set. Set in environment or in wscript.')
        fail = True

    ok = check_and_set_var('GOOS', v, ['darwin', 'linux', 'nacl'])
    if not ok:
        error('GOOS is set to `%s\', must be either darwin, linux or nacl.')
        fail = True

    ok = check_and_set_var('GOARCH', v, ['amd64', '386', 'arm'])
    if not ok:
        error('GOARCH is set to `%s\', must be either amd64, 386 or arm.')
        fail = True

    if fail:
        error('Set in environment or in wscript')
        exit(1)

    arch_dict = {
        'arm':   '5',
        'amd64': '6',
        '386':   '8',
    }
    v['GOARCH_O'] = arch_dict[v['GOARCH']]

@conftest
def find_gc(conf):
    v = conf.env
    O = v['GOARCH_O']

    conf.find_program(O+'a', var='AS')
    conf.find_program(O+'c', var='CC')
    conf.find_program(O+'g', var='GC', mandatory=True)
    conf.find_program(O+'l', var='LD', mandatory=True)
    conf.find_program('gopack', var='GOPACK', mandatory=True)
    conf.find_program('gofmt', var='GOFMT', mandatory=True)
    conf.find_program('gotest', var='GOTEST')
    conf.find_program('godoc', var='GODOC')
    conf.find_program('cgo', var='CGO')

@conftest
def common_flags_gc(conf):
    v = conf.env

    v['GOFLAGS']      = []
    v['GO_TGT_F']     = '-o'
    v['GOPATH_ST']    = '-I%s'

    v['GOLDFLAGS']    = [] 
    v['GOLD_TGT_F']   = '-o'
    v['GOPKGPATH_ST'] = '-L%s'

    v['GOPACK_TGT_F']   = ''
    v['GOPACKFLAGS']  = 'grc'

    v['GOFMTFLAGS']   = []

@conftest
def go_platform_flags(conf):
    v = conf.env

    v['GOOBJEXT'] = '.'+v['GOARCH_O']
    v['GOPKGEXT'] = '.a'


def detect(conf):
    conf.go_vars()
    conf.find_gc()
    conf.common_flags_gc()
    conf.go_platform_flags()


###############################
# Building
###############################

@feature('go')
@before('apply_core')
def init_go(self):
    Utils.def_attrs(
        self,
        packages          = {},
        deps              = {},
        format_task       = None,
        _format           = False,
        usepkg            = '',
        usepkg_local      = ''
    )

    opt = Options.options
    if opt.gofmt != False or getattr(self, 'format', False) \
                          or getattr(self, 'format_list', False):
        self._format = True
    if (opt.gofmt == 'list' or getattr(self, 'format_list', None)) \
       and not opt.gofmt == 'format':
        self.env.append_unique('GOFMTFLAGS', '-l')

@feature('go')
@after('init_go')
@before('apply_core')
def apply_go_scan(self):
    sources = self.to_list(self.source)
    inputs = [self.path.find_resource(s) for s in sources]
    gp = GoParser(self)
    gp.start(inputs)
    debug('found packages: %s' % ' '.join(gp.packages.keys()))
    debug('found dependencies: %s' % gp.deps)
    self.deps = gp.deps
    for pkg, nodes in gp.packages.iteritems():
        gopkg = GoPackage(pkg, nodes)
        self.packages[pkg] = gopkg
        if pkg == 'main':
            gopkg.target = getattr(self, 'target', pkg)

@feature('goprogram')
@after('init_go')
@before('apply_core')
def var_target_goprogram(self):
    self.default_install_path = '${PREFIX}/bin'
    self.default_chmod = 0755

@feature('gopkg')
@after('init_go')
@before('apply_core')
def var_target_gopkg(self):
    import os.path, os
    self.default_install_path = os.path.join(self.env['GOROOT'], 'pkg',
                                             self.env['GOOS'] + '_' +
                                             self.env['GOARCH'])

@extension(EXT_GO)
def go_hook(self, node):
    if self._format == True:
        if not self.format_task:
            self.format_task = self.create_task('goformat', [node], [])
        else:
            self.format_task.set_inputs(node)

@feature('go')
@after('apply_core')
def apply_go_build(self):
    for pkg in self.packages.itervalues():
        output = self.path.find_or_declare(pkg.target + self.env['GOOBJEXT'])
        pkg.build_task = self.create_task('gocompile', pkg.inputs, output)

    for pkg, deps in self.deps.iteritems():
        for dep in deps:
            debug('run build of %s after %s' % (pkg, dep))
            self.packages[pkg].build_task.set_run_after(self.packages[dep].build_task)

@feature('goprogram')
@after('apply_go_build')
def apply_go_link(self):
    main = self.packages['main']
    if not main:
        error('Could not find a `main\' package')
        exit(1)
    main
    output = self.path.find_or_declare(main.target)
    main.link_task = self.create_task('golink', main.build_task.outputs, output)

@feature('gopkg')
@after('apply_go_build')
def apply_go_pack(self):
    for pkg in self.packages.itervalues():
        output = self.path.find_or_declare(pkg.target + self.env['GOPKGEXT'])
        pkg.pack_task = self.create_task('gopack', pkg.build_task.outputs, output)

@feature('go')
@after('apply_go_link', 'apply_go_pack')
def apply_go_deps(self):
    for pkg, deps in self.deps.iteritems():
        for dep in deps: 
            task = self.packages[dep].build_task
            path = task.outputs[0].bld_dir(task.env)
            self.env.append_unique('GOFLAGS', self.env['GOPATH_ST'] % path)

@feature('go')
@after('apply_go_deps')
def apply_go_usepkg(self):
    """Add dependencies on packages the task depends on."""
    names = self.to_list(self.usepkg_local)
    seen = set([])
    tmp = Utils.deque(names) # consume a copy of the list of names
    while tmp:
        pkg_name = tmp.popleft()
        # visit dependencies only once
        if pkg_name in seen:
            continue

        tg = self.name_to_obj(pkg_name)
        if not tg:
            raise Utils.WafError('object %r was not found in usepkg_local (required by %r)' % (pkg_name, self.name))
        seen.add(pkg_name)
        # Post the task_gen so it can create its tasks, which we'll need
        tg.post()

        if pkg_name not in tg.packages:
            error('task_gen %r does not build a package %s' % (tg, pkg_name))
            exit(1)
        dep_pkg = tg.packages[pkg_name]

        # Add link flags
        path = dep_pkg.build_task.outputs[0].bld_dir(tg.env)
        self.env.append_unique('GOFLAGS', self.env['GOPATH_ST'] % path)

        # Set run order
        for pkg in self.packages.itervalues():
            pkg.build_task.set_run_after(dep_pkg.build_task)

            # Add dependencies
            dep_nodes = getattr(pkg.build_task, 'dep_nodes', [])
            pkg.build_task.dep_nodes = dep_nodes + dep_pkg.build_task.outputs

    pkgs = self.to_list(self.usepkg)
    for pkg in pkgs:
        if 'PKGPATH_'+pkg in self.env:
            path = self.env['PKGPATH_'+pkg]
            self.env.append_unique('GOFLAGS', self.env.GOPATH_ST % path)
            self.env.append_unique('GOLDFLAGS', self.env.GOPKGPATH_ST % path)


@feature('goprogram', 'gopkg')
@after('apply_go_link', 'apply_go_pack')
def default_go_install(self):
    for pkg in self.packages.itervalues():
        task = pkg.link_task or pkg.pack_task
        if self.install_path and task:
            self.bld.install_files(
                self.install_path,
                task.outputs[0],
                env=self.env,
                chmod=self.chmod
            )


Task.simple_task_type(
    'goformat',
    '${GOFMT} ${GOFMTFLAGS} -w ${SRC}',
    'PINK'
).quiet = True

Task.simple_task_type(
    'gocompile',
    '${GC} ${GOFLAGS} ${GO_TGT_F}${TGT} ${SRC}',
)

Task.simple_task_type(
    'golink',
    '${LD} ${GOLDFLAGS} ${GOLD_TGT_F}${TGT} ${SRC}',
    'YELLOW',
    after = 'gocompile'
)

Task.simple_task_type(
    'gopack',
    '${GOPACK} ${GOPACKFLAGS} ${GOPACK_TGT_F}${TGT} ${SRC}',
    'YELLOW',
    after = 'gocompile'
)
