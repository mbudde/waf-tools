#
# go.py - Waf tool for compiling Go source code.
#
# Written by Michael Budde <mbudde@gmail.com> (2009).
#
"""

def set_options(opt):
    opt.tool_options('go', tooldir='/path/to/go.py')

def configure(conf):
    conf.check_tool('go', tooldir='/path/to/go.py')

def build(bld):
    bld.new_task_gen(
        features = 'go gopkg',
        source = 'foo.go foo2.go',
        target = 'foo'
    )
    bld.new_task_gen(
        features = 'go goprogram',
        source = 'main.go',
        target = 'bar',
        usepkg_local = 'foo',
        format = True  # Run sources through gofmt before compiling
    )

"""

import os
import Task, Utils, Options
from Configure import conftest
from TaskGen import taskgen, feature, before, after, extension
from Logs import debug, error

EXT_GO = ['.go']


@feature('go')
@before('apply_core')
def init_go(self):
    Utils.def_attrs(
        self,
        compilation_task=None,
        link_task=None,
        pack_task=None,
        format_task=None,
        usepkg_local=''
    )

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

        if getattr(tg, 'pack_task', None):
            # Add link flags
            path = tg.pack_task.outputs[0].bld_dir(tg.env)
            self.env.append_unique('GOFLAGS', self.env.GOPATH_ST % path)
            self.env.append_unique('GOLDFLAGS', self.env.GOPKGPATH_ST % path)

            task = getattr(self, 'link_task', None)
            if not task: task = getattr(self, 'pack_task', None)
            if task:
                # Set run order
                self.compilation_task.set_run_after(tg.compilation_task)
                task.set_run_after(tg.pack_task)

                # Add dependencies
                dep_nodes = getattr(task, 'dep_nodes', [])
                task.dep_nodes = dep_nodes + tg.pack_task.outputs


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
    if Options.options.gofmt == True or getattr(self, 'format', False):
        if not self.format_task:
            self.format_task = self.create_task('goformat', [node], [])
        else:
            self.format_task.inputs.append(node)
        


@conftest
def find_gc(conf):
    v = conf.env
    arch_dict = {
        'arm':   '5',
        'amd64': '6',
        '386':   '8',
    }
    arch = os.environ['GOARCH']
    if arch not in arch_dict:
        debug.Error('$GOARCH should be set to either amd64, 386 or arm')
    O = arch_dict[arch]
    v['GOARCH'] = O

    conf.find_program(O+'a', var='AS')
    conf.find_program(O+'c', var='CC')
    conf.find_program(O+'g', var='GC', mandatory=True)
    conf.find_program(O+'l', var='LD', mandatory=True)
    conf.find_program('gopack', var='GOPACK', mandatory=True)
    conf.find_program('gofmt', var='GOFMT')
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

@conftest
def go_platform_flags(conf):
    v = conf.env

    v['GOOBJEXT'] = '.'+v['GOARCH']
    v['GOPKGEXT'] = '.a'


def detect(conf):
    conf.find_gc()
    conf.common_flags_gc()
    conf.go_platform_flags()

def set_options(opt):
    opt.add_option('--gofmt', action='store_true', default=False,
                   help='Run source code through gofmt before compiling')

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
