#
# go.py - Waf tool for compiling Go source code.
#
# Written by Michael Budde <mbudde@gmail.com> (2009).
#

import os
import Task, Utils, Options
from Configure import conftest
from TaskGen import feature, before, after, extension
from Logs import debug, error

EXT_GO = ['.go']


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
        import sys
        sys.exit(1)

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
        compilation_task = None,
        link_task        = None,
        pack_task        = None,
        format_task      = None,
        usepkg_local     = '',
        _format          = False
    )
    opt = Options.options
    if opt.gofmt != False or getattr(self, 'format', False) \
                          or getattr(self, 'format_list', False):
        self._format = True
    if (opt.gofmt == 'list' or getattr(self, 'format_list', None)) \
       and not opt.gofmt == 'format':
        self.env.append_unique('GOFMTFLAGS', '-l')

@feature('goprogram')
@before('apply_core')
@after('init_go')
def var_target_goprogram(self):
    self.default_install_path = '${PREFIX}/bin'
    self.default_chmod = 0755

@feature('gopkg')
@before('apply_core')
@after('init_go')
def var_target_gopkg(self):
    import os.path, os
    self.default_install_path = os.path.join(self.env['GOROOT'], 'pkg',
                                             self.env['GOOS'] + '_' +
                                             self.env['GOARCH'])

@feature('goprogram', 'gopkg')
@after('apply_go_link', 'apply_go_pack')
def default_go_install(self):
    """you may kill this method to inject your own installation for the first element
    any other install should only process its own nodes and not those from the others"""
    task = getattr(self, 'pack_task', None)
    if not task: task = getattr(self, 'link_task', None)
    if self.install_path and task:
        self.bld.install_files(self.install_path, task.outputs[0], env=self.env, chmod=self.chmod)

@feature('go')
@after('apply_go_link', 'apply_go_pack')
def apply_go_pkgs(self):
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

        tgtask = getattr(tg, 'pack_task', None) or getattr(tg, 'compilation_task', None)
        if not tgtask:
            return
        # Add link flags
        path = tgtask.outputs[0].bld_dir(tg.env)
        self.env.append_unique('GOFLAGS', self.env.GOPATH_ST % path)
        #self.env.append_unique('GOLDFLAGS', self.env.GOPKGPATH_ST % path)

        task = getattr(self, 'link_task', None)
        if not task: task = getattr(self, 'pack_task', None)
        if task:
            # Set run order
            self.compilation_task.set_run_after(tg.compilation_task)
            if tgtask != tg.compilation_task:
                task.set_run_after(tgtask)

            # Add dependencies
            dep_nodes = getattr(task, 'dep_nodes', [])
            task.dep_nodes = dep_nodes + tgtask.outputs

@feature('goprogram')
@after('apply_core')
def apply_go_link(self):
    if not self.compilation_task:
        return
    self.link_task = self.create_task(
        'golink',
        self.compilation_task.outputs,
        self.path.find_or_declare(self.target)
    )

@feature('gopkg')
@after('apply_core')
def apply_go_pack(self):
    if not self.compilation_task:
        return
    self.pack_task = self.create_task(
        'gopack',
        self.compilation_task.outputs,
        self.path.find_or_declare(self.target + self.env['GOPKGEXT'])
    )

@extension(EXT_GO)
def go_hook(self, node):
    if not self.compilation_task:
        self.compilation_task = self.create_task(
            'gocompile',
            [node],
            self.path.find_or_declare(self.target + self.env['GOOBJEXT'])
        )
    else:
        self.compilation_task.inputs.append(node)
    if self._format == True:
        if not self.format_task:
            self.format_task = self.create_task('goformat', [node], [])
        else:
            self.format_task.inputs.append(node)
        


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
