#
# Copyright 2023 Delphix
# Copyright 2021 Datto, Inc.
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
import textwrap
from typing import Iterable, List, Optional

import drgn
import sdb
from sdb.commands.internal.table import Table
from sdb.commands.zfs.internal import gethrtime, removeprefix, NANOSEC, MSEC


class Zio(sdb.Locator, sdb.PrettyPrinter):
    """
    Iterate and pretty-print ZIOs

    EXAMPLES
        Print all parent ZIOs on the system following their hierarchy
        of children:

            sdb> zio -r
            ADDRESS                        TYPE  STAGE            WAITER             TIME_ELAPSED
            -------------------------------------------------------------------------------------
            0xffff8f16579cc520             NULL  OPEN             -                             -
            0xffff8f16579cca10             NULL  OPEN             -                             -
            0xffff8f165ae07680             NULL  CHECKSUM_VERIFY  0xffff8f14b2bc0000            -
             0xffff8f165ae02780            READ  VDEV_IO_START    -                             -
              0xffff8f165ae06ca0           READ  VDEV_IO_START    -                         133ms
            0xffff8f165d8fa290             NULL  OPEN             -                             -
            0xffff8f165d8fd8e0             NULL  CHECKSUM_VERIFY  0xffff8f14b2bc3d00            -
            ...

        Follow the parent hierarchy of a specific ZIO:

            sdb> echo 0xffff8f165ae06ca0 | zio -p
            -------------------------------------------------------------------------------------
            ADDRESS                        TYPE  STAGE            WAITER             TIME_ELAPSED
            0xffff8f165ae06ca0             READ  VDEV_IO_START    -                         133ms
             0xffff8f165ae02780            READ  VDEV_IO_START    -                             -
              0xffff8f165ae07680           NULL  CHECKSUM_VERIFY  0xffff8f14b2bc0000            -
    """

    names = ["zio"]
    input_type = "zio_t *"
    output_type = "zio_t *"
    load_on = [sdb.Module("zfs"), sdb.Library("libzpool")]

    @classmethod
    def _init_parser(cls, name: str) -> argparse.ArgumentParser:
        parser = super()._init_parser(name)
        parser.add_argument("-z", "--graphviz", action='store_true')
        parser.add_argument("-r", "--recursive", action='store_true')
        parser.add_argument("-c", "--children", action='store_true')
        parser.add_argument("-p", "--parents", action='store_true')
        parser.add_argument('-o',
                            metavar="FIELDS",
                            help='comma-separated list of fields to display')
        parser.add_argument('-v',
                            action='store_true',
                            help='Print all statistics')

        #
        # We change the formatter so we can add newlines in the epilog.
        #
        parser.formatter_class = argparse.RawDescriptionHelpFormatter
        parser.epilog = textwrap.fill(
            f"FIELDS := {', '.join(Zio.FIELDS.keys())}\n",
            width=80,
            replace_whitespace=False)
        parser.epilog += "\n\n"
        parser.epilog += textwrap.fill(
            ("If -o is not specified the default fields used are "
             f"{', '.join(Zio.DEFAULT_FIELDS)}.\n"),
            width=80,
            replace_whitespace=False)
        return parser

    def __pp_fmt_addr(obj):
        return hex(obj.value_())
    def __pp_fmt_addr_null(obj):
        if sdb.is_null(obj):
            return "-"
        return hex(obj.value_())

    def __pp_fmt_symbol(obj):
        if sdb.is_null(obj):
            return "-"
        return obj.format_(symbolize=True, type_name=False).split('+', 1)[0]

    def __pp_fmt_task(obj):
        if sdb.is_null(obj):
            return "-"
        task = drgn.cast("struct task_struct *", obj)
        return f"{task.comm.string_().decode()}:{task.pid.value_()} {hex(obj.value_())}"

    def __pp_fmt_enum(obj, prefix):
        return removeprefix(obj.format_(type_name=False), prefix)

#    def __pp_fmt_enum_bits(obj):
#        v = obj.value_()
#        ty = sdb.get_type(sdb.type_canonical_name(obj.type_))
#        bits = []
#        for name, bit in ty.enumerators:
#            if v & (1 << bit):
#                bits.append(name)
#        return f"{'|'.join(bits)}"

    def __pp_fmt_flags(obj, names: List[str]):
        v = obj.value_()
        bits = []

        bit = 0
        bitv = 1
        while bitv <= v:
            if v & bitv:
                bits.append(names[bit])
            bit += 1
            bitv = 1 << bit
        return f"{'|'.join(bits)}"

    def __pp_fmt_delta(zio):
        if zio.io_timestamp == 0:
            return "-"
        delta_ms = (gethrtime() - int(zio.io_timestamp)) / (NANOSEC / MSEC)
        return f"{str(int(delta_ms))}ms"

    _flag_names = [
        "DONT_AGGREGATE",  "IO_REPAIR",       "SELF_HEAL",        "RESILVER",
        "SCRUB",           "SCAN_THREAD",     "PHYSICAL",         "CANFAIL",
        "SPECULATIVE",     "CONFIG_WRITER",   "DONT_RETRY",       "[UNUSED 11]",
        "NODATA",          "INDUCE_DAMAGE",   "ALLOC_THROTTLED",  "IO_RETRY",
        "PROBE",           "TRYHARD",         "OPTIONAL",         "DIO_READ",
        "DONT_QUEUE",      "DONT_PROPAGATE",  "IO_BYPASS",        "IO_REWRITE",
        "RAW_COMPRESS",    "RAW_ENCRYPT",     "GANG_CHILD",       "DDT_CHILD",
        "GODFATHER",       "NOPWRITE",        "REEXECUTED",       "DELEGATED",
        "PREALLOCATED",    "GROUP_LEADER",
    ]
    _flag_names_short = [
        "DA", "RP", "SH", "RS", "SC", "ST", "PH", "CF",
        "SP", "CW", "DR", "??", "ND", "ID", "AT", "RE",
        "PR", "TH", "OP", "RD", "DQ", "DP", "BY", "RW",
        "CM", "EN", "GG", "DD", "GF", "NP", "EX", "DG",
        "PA", "GL",
    ]

    _post_names = [ "REEXECUTE", "SUSPEND", "DIO_CHKSUM_ERR" ]

    FIELDS = {
        "address": __pp_fmt_addr,
        "type": lambda zio: Zio.__pp_fmt_enum(zio.io_type, "ZIO_TYPE_"),
        "stage": lambda zio: Zio.__pp_fmt_enum(zio.io_stage, "ZIO_STAGE_"),
        "waiter": lambda zio: Zio.__pp_fmt_addr_null(zio.io_waiter),
        "delta": __pp_fmt_delta,

        "flags=long": lambda zio: Zio.__pp_fmt_flags(zio.io_flags, Zio._flag_names),
        "flags=short": lambda zio: Zio.__pp_fmt_flags(zio.io_flags, Zio._flag_names_short),

        "child_type": lambda zio: Zio.__pp_fmt_enum(zio.io_child_type, "ZIO_CHILD_"),

        "post": lambda zio: Zio.__pp_fmt_flags(zio.io_post, Zio._post_names),
    }

    FIELDS["flags"] = FIELDS["flags=long"]

    DEFAULT_FIELDS = [
        "address",
        "type",
        "stage",
        "waiter",
        "delta",
    ]

    def __pp_parse_args(self) -> List[str]:
        fields = Zio.DEFAULT_FIELDS
        if self.args.o:
            fields = self.args.o.split(",")
        elif self.args.v:
            fields = list(Zio.FIELDS.keys())

        for field in fields:
            if field not in Zio.FIELDS:
                raise sdb.CommandError(self.name,
                                       f"'{field}' is not a valid field")

        return fields

    def __init__(self,
                 args: Optional[List[str]] = None,
                 name: str = "_") -> None:
        super().__init__(args, name)
        self.level = 0
        self.seen = []

    def __removeopt(field):
        p = field.find("=")
        return field[:p] if p >= 0 else field

    def _graphviz_print(self, objs: Iterable[drgn.Object]) -> None:
        print(
            "strict digraph {\n"
            "rankdir=\"BT\"")

        last = []
        for obj in objs:
            id = Zio.__pp_fmt_addr(obj)
            if not id in self.seen:
                self.seen.append(id)
                print(f'"{id}" [label="{Zio.FIELDS["type"](obj)}\\l{Zio.FIELDS["flags=short"](obj)}"]')

        print("}\n")

    def _pretty_print(self, objs: Iterable[drgn.Object]) -> None:
        fields = self.__pp_parse_args()
        table = Table([Zio.__removeopt(field) for field in fields], None, {})
        for obj in objs:
            row_dict = {
                Zio.__removeopt(field): Zio.FIELDS[field](obj) for field in set(fields) - {"address"}
            }
            row_dict["address"] = f'{" " * self.level}{Zio.FIELDS["address"](obj)}'
            table.add_row("address", row_dict)
        table.print_(print_headers=True)

    def pretty_print(self, objs: Iterable[drgn.Object]) -> None:
        if self.args.graphviz:
            return self._graphviz_print(objs)
        return self._pretty_print(objs)

    @sdb.InputHandler("zio_t*")
    def from_zio(self, zio: drgn.Object) -> Iterable[drgn.Object]:
        yield zio
        self.level += 1
        if self.level < 2 or self.args.recursive:
            zios = []
            if self.args.children:
                zios = [zl.zl_child for zl in sdb.execute_pipeline(
                    [zio.io_child_list.address_of_()],
                    [sdb.Walk(), sdb.Cast(["zio_link_t *"])],
                )]
            elif self.args.parents:
                zios = [zl.zl_parent for zl in sdb.execute_pipeline(
                    [zio.io_parent_list.address_of_()],
                    [sdb.Walk(), sdb.Cast(["zio_link_t *"])],
                )]
            for zio in zios:
                yield from self.from_zio(zio)
        self.level -= 1

    @staticmethod
    def zio_has_parents(zio: drgn.Object) -> bool:
        parent_list = zio.io_parent_list.list_head.address_of_()
        first_parent = parent_list.next
        if parent_list != first_parent:
            return True
        return False

    def no_input(self) -> drgn.Object:
        if self.args.parents:
            raise sdb.CommandInvalidInputError(
                self.name, "command argument -p is not applicable " +
                " when printing all parent ZIOs")

        zio_cache = drgn.cast("spl_kmem_cache_t *", sdb.get_object("zio_cache"))
        zios = sdb.execute_pipeline(
            [zio_cache.skc_linux_cache],
            [sdb.Walk(), sdb.Cast(["zio_t *"])],
        )
        for zio in zios:
            if not self.zio_has_parents(zio):
                yield from self.from_zio(zio)
