import re
import hashlib
import sys

pin_assignments = {}
mcu_model = None

if len(sys.argv) != 2:
    print("usage: python convert.py <input_file>")
    quit(1)

[_, input_path] = sys.argv

with open(input_path, "r") as f:
    input_hash = hashlib.sha256(f.read().encode("utf-8")).hexdigest()

with open(input_path, "r") as f:
    state = None
    for l in f:
        if l.startswith("MCU") and mcu_model is None:
            mcu_model = l.split("\t")[1].strip()
        if l.startswith("Pin Nb"):
            state = "pin_parsing"
            continue
        if state == "pin_parsing":
            [pin, number, function, _] = l.split("\t")
            pin_assignments[pin] = function
    pass

lp_re = "(?P<LP>\()"
rp_re = "(?P<RP>\))"
name_re = "(?P<NAME>[a-zA-Z]\w*)"
digit_re = "(?P<DIGIT>[+-]?(?:\d*\.)?\d+)"
string_re = '(?P<STRING>"(?:\\\\"|[^"])*")'
lexer_re = re.compile(
    f"{string_re}|{name_re}|{digit_re}|{lp_re}|{rp_re}|(?P<IGNORE>(\s|\\n)*)"
)


def to_token(d):
    if len(list(filter(lambda x: x, [x is not None for x in d.values()]))) > 1:
        raise Exception(f"{d} has multiple matches")
    for key in d.keys():
        if d[key] is not None and key != "IGNORE":
            return (key, d[key])


def get_token(stream):
    token = to_token(next(stream).groupdict())
    if token:
        return token
    else:
        return get_token(stream)


class StringToken:
    def __init__(self, s):
        self.s = s

    def str(self):
        self.__repr__()

    def __repr__(self):
        return f'"{self.s}"'


class Node:
    @staticmethod
    def build(node_name, stream):
        kids = []
        try:
            while True:
                token = get_token(stream)
                (name, _) = token
                if name == "RP":
                    break
                elif name == "LP":
                    token = get_token(stream)
                    if token[0] != "NAME":
                        raise Exception(f"Node can not start with a {token} token")
                    kids.append(Node.build(token[1], stream))
                elif name == "STRING":
                    kids.append(StringToken(token[1][1:-1]))
                else:
                    kids.append(token[1])
        except StopIteration:
            pass
        return Node(node_name, kids)

    def __init__(self, name, kids):
        self.name = name
        self.kids = kids

    def list_symbols(self):
        if self.name == "symbol":
            print(self.kids[0])
        for k in self.kids:
            if isinstance(k, Node):
                k.list_symbols()

    def get_symbol(self, target):
        if self.name == "symbol" and self.kids[0].s.startswith(target):
            return self
        return self.find(lambda x: x.get_symbol(target))

    def rewrite_symbol(self):
        pins = self.find_all_by_name("pin")
        for pin in pins:
            pin.rewrite_pin()

    def rewrite_pin(self):
        if self.name != "pin":
            raise Exception("Can't change shit that ain't a pin")
        pin_nr = self.get_pin_nr().s
        if pin_nr in pin_assignments:
            pin_name_node = self.get_by_name("name")
            print(
                f"Renaming pin {pin_nr} from {pin_name_node.kids[0]} to {pin_assignments[pin_nr]}"
            )
            pin_name_node.kids[0] = pin_assignments[pin_nr]

    def get_pin_nr(self):
        if self.name == "number":
            return self.kids[0]
        return self.find(lambda x: x.get_pin_nr())

    def get_by_name(self, name):
        if self.name == name:
            return self
        return self.find(lambda x: x.get_by_name(name))

    def find_all_by_name(self, name):
        if self.name == name:
            return [self]
        res = []
        for k in self.kids:
            if isinstance(k, Node):
                res = [*res, *k.find_all_by_name(name)]
        return res

    def find(self, fn):
        for k in self.kids:
            if isinstance(k, Node):
                res = fn(k)
                if res:
                    return res

    def str(self):
        return self.__repr__()

    def __repr__(self):
        return f'({self.name} {" ".join([str(k) for k in self.kids])})'


with open("/usr/share/kicad/symbols/MCU_ST_STM8.kicad_sym", "r") as f:
    input = f.read()

    stream = re.finditer(lexer_re, input)
    tree = Node.build("start", stream)
    mcu_symbol = tree.get_symbol(mcu_model.rstrip("x"))
    if mcu_symbol is None:
        print(f"No suitable symbol was found for a {mcu_model} name")
        quit(1)
    mcu_symbol.rewrite_symbol()
    modified_id = f"{mcu_symbol.kids[0].s}_{input_hash[:8]}"
    # mcu_symbol.kids[0].s = modified_id

    wrapper = Node(
        "kicad_symbol_lib",
        [
            Node("version", [tree.kids[0].kids[0].kids[0]]),
            Node("generator", [StringToken("STMCube_to_KiCad")]),
        ],
    )

    wrapper.kids.append(mcu_symbol)
    with open(f"{modified_id}.kicad_sym", "w") as of:
        of.write(str(wrapper))
    print(f"New symbol written to {modified_id}.kicad_sym")
