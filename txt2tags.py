# encoding: utf-8

# txt2tags.py - Task for compiling txt2tags files.
# Copyright (C) 2009 Michael Budde

import Task, Utils
from TaskGen import taskgen, feature, before
from Logs import debug

targets = ('html', 'xhtml', 'tex', 'sgml', 'man', 'mgp', 'pm6', 'txt')

@taskgen
@feature('txt2tags')
@before('apply_core')
def apply_txt2tags(self):
    try:
        if self.target == '':
            raise AttributeError
        if not self.target in targets:
            raise Utils.WafError("target `%s' is not supported by txt2tags" %
                                 self.target)
        self.env['TXT2TAGSTARGET'] = self.target
        debug('txt2tags: target is %s' % self.target)
        debug('txt2tags: env is %s' % self.env)
    except AttributeError:
        raise Utils.WafError("no target given in `%s' task" %
                             getattr(self, 'name', 'txt2tags'))
    sources = self.to_list(self.source)
    for filename in sources:
        node = self.path.find_resource(filename)
        if not node:
            raise Utils.WafError('cannot find %s' % filename)
        task = self.create_task('txt2tags')
        task.set_inputs(node)
        ext_out = getattr(self, 'ext_out', '.'+self.target)
        task.set_outputs(node.change_ext(ext_out))
        task.env = self.env
        task.curdirnode = self.path
    self.source = []

def detect(conf):
    conf.find_program('txt2tags', var='TXT2TAGS', mandatory=True)
    conf.env['TXT2TAGSFLAGS'] = ''

Task.simple_task_type(
    'txt2tags',
    '${TXT2TAGS} ${TXT2TAGSFLAGS} -t ${TXT2TAGSTARGET} -o ${TGT} ${SRC}')
