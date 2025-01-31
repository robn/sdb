#
# Copyright 2025 Klara, Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#

# pylint: disable=missing-docstring

import argparse
from typing import Dict, Iterable, List, Optional, Tuple
from collections import defaultdict

import drgn
from drgn.helpers.linux.list import list_for_each_entry
from drgn.helpers.linux.pid import for_each_task
from drgn.helpers.linux.sched import task_state_to_char

import sdb


class KernelStackFrame(sdb.SingleInputCommand):
    """
    """

    names = ["frame", "frames"]
    input_type = "struct task_struct *"
    load_on = [sdb.Kernel()]

    def __init__(self,
                 args: Optional[List[str]] = None,
                 name: str = "_") -> None:
        super().__init__(args, name)

    @classmethod
    def _init_parser(cls, name: str) -> argparse.ArgumentParser:
        parser = super()._init_parser(name)
        parser.add_argument("frame", nargs="?", type=int)
        parser.add_argument("var", nargs="?", type=str)
        return parser

    def _call_one(self, task: drgn.Object) -> Optional[Iterable[drgn.Object]]:
        frames = sdb.get_prog().stack_trace(task)

        if self.args.frame == None:
            for frame in frames:
                print(frame)
            return

        frame = frames[self.args.frame]
        if self.args.var == None:
            print(frame)
            return

        if not self.args.var in frame.locals():
            raise sdb.CommandError(
                self.name,
                f"'{self.args.var}' not found in frame")

        var = frame[self.args.var]
        if var.absent_:
            raise sdb.CommandError(
                self.name,
                f"'{self.args.var}' was optimised out")

        yield var
