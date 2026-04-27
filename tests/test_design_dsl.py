# -*- coding: utf-8 -*-

# This code is part of Qiskit.
#
# (C) Copyright IBM 2017, 2021.
#
# This code is licensed under the Apache License, Version 2.0. You may
# obtain a copy of this license in the LICENSE.txt file in the root directory
# of this source tree or at http://www.apache.org/licenses/LICENSE-2.0.
#
# Any modifications or derivative works of this code must retain this
# copyright notice, and modified files need to carry a notice indicating
# that they have been altered from the originals.

"""Tests for the YAML design DSL (qiskit_metal.toolbox_metal.design_dsl).

分三组：

1. **纯展开/校验**：不需要实例化 qiskit_metal 类，覆盖 `$for` / `$extend` /
   `${var}` 插值 / route 简记 / 错误路径。
2. **JSON Schema**：用 jsonschema 校验示例 YAML 通过、几条反例被抓到。
   未安装 jsonschema 时整组 skip。
3. **端到端**：调用 `build_design()` 把 4-qubit demo 真正实例化，验证
   组件数与 pin 名。

第 3 组依赖 qiskit_metal 完整可 import 与 PySide 等可选依赖；任何 import
失败时整组 skip。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from qiskit_metal.toolbox_metal import design_dsl as dsl
from qiskit_metal.toolbox_metal.design_dsl import (DesignDslError,
                                                    _expand_list,
                                                    _inflate_route,
                                                    _walk_substitute)

REPO_ROOT = Path(__file__).resolve().parent.parent
EXAMPLE_YAML = REPO_ROOT / "examples" / "dsl" / "2x2_4qubit.metal.yaml"
# schema 跟 loader 一起住在源码树，schema_path() 返回的就是它。
SCHEMA_FILE = dsl.schema_path()


# ---------------------------------------------------------------------------
# 1. 纯展开 / 校验
# ---------------------------------------------------------------------------


def _expand(yaml_text, *, vars=None, templates=None):
    """工具：把一段 YAML 文本里的 components 展开为最终 spec 列表。"""
    raw = yaml.safe_load(yaml_text)
    return _expand_list(raw["components"], vars or {}, templates or {})


def test_for_loop_expands_to_n_items():
    specs = _expand("""
components:
  - $for:
      - {name: A}
      - {name: B}
      - {name: C}
    name: ${name}
    class: TransmonPocket
    options: {}
""")
    assert [s["name"] for s in specs] == ["A", "B", "C"]


def test_for_loop_substitutes_iter_vars():
    specs = _expand("""
components:
  - $for:
      - {name: Q1, x: 1mm}
      - {name: Q2, x: 2mm}
    name: ${name}
    class: TransmonPocket
    options:
      pos_x: ${x}
""")
    assert specs[0]["options"]["pos_x"] == "1mm"
    assert specs[1]["options"]["pos_x"] == "2mm"


def test_for_loop_indirect_var_resolves_against_outer_vars():
    """iter var 自身含 ${...} 时，应先用外层 ctx 解析再喂进循环体。

    回归：早期实现里 iter_var ``x: "-${qx}"`` 在循环体里被 ``${x}`` 引用时
    只展开一层，结果 pos_x 仍是 "-${qx}" 而不是 "-1.55mm"。
    """
    specs = _expand("""
components:
  - $for:
      - {name: Q1, x: "-${qx}"}
      - {name: Q2, x: "+${qx}"}
    name: ${name}
    class: TransmonPocket
    options:
      pos_x: ${x}
""", vars={"qx": "1.55mm"})
    assert specs[0]["options"]["pos_x"] == "-1.55mm"
    assert specs[1]["options"]["pos_x"] == "+1.55mm"


def test_extend_deep_merges_template():
    templates = {
        "qubit": {
            "class": "TransmonPocket",
            "options": {
                "pad_width": "425um",
                "pad_height": "90um",
                "connection_pads": {
                    "readout": {"loc_W": "+1", "loc_H": "+1"}
                }
            }
        }
    }
    specs = _expand("""
components:
  - $extend: qubit
    name: Q1
    options:
      pad_width: 500um            # 覆盖
      pos_x: 1mm                  # 新增
      connection_pads:
        readout: {pad_width: 180um}  # 嵌套合并
        bus: {loc_W: "-1"}             # 新增子键
""", templates=templates)
    opts = specs[0]["options"]
    assert opts["pad_width"] == "500um"        # 子覆盖父
    assert opts["pad_height"] == "90um"        # 父保留
    assert opts["pos_x"] == "1mm"              # 新增
    pads = opts["connection_pads"]
    # readout 是嵌套合并，loc_W 来自父，pad_width 来自子
    assert pads["readout"]["loc_W"] == "+1"
    assert pads["readout"]["loc_H"] == "+1"
    assert pads["readout"]["pad_width"] == "180um"
    # bus 是新加的 pin
    assert pads["bus"]["loc_W"] == "-1"


def test_extend_chain_resolves():
    templates = {
        "base": {"class": "TransmonPocket", "options": {"pad_width": "425um"}},
        "derived": {"$extend": "base", "options": {"pad_height": "90um"}},
    }
    specs = _expand("""
components:
  - $extend: derived
    name: Q1
    options: {pos_x: 1mm}
""", templates=templates)
    opts = specs[0]["options"]
    assert opts["pad_width"] == "425um"
    assert opts["pad_height"] == "90um"
    assert opts["pos_x"] == "1mm"
    assert specs[0]["class"] == "TransmonPocket"


def test_extend_cycle_raises():
    templates = {
        "a": {"$extend": "b"},
        "b": {"$extend": "a"},
    }
    with pytest.raises(DesignDslError, match="循环"):
        _expand("""
components:
  - $extend: a
    name: Q1
    class: TransmonPocket
""", templates=templates)


def test_unknown_var_raises():
    with pytest.raises(DesignDslError, match="未知"):
        _expand("""
components:
  - name: Q1
    class: TransmonPocket
    options:
      pos_x: "${nope}"
""")


def test_unknown_template_raises():
    with pytest.raises(DesignDslError, match="未知模板"):
        _expand("""
components:
  - $extend: missing
    name: Q1
    class: TransmonPocket
""")


def test_route_from_to_inflates_pin_inputs():
    spec = _inflate_route({
        "name": "bus",
        "from": "Q1.bus_h",
        "to": "Q2.bus_h",
        "options": {"total_length": "5mm"},
    })
    pi = spec["options"]["pin_inputs"]
    assert pi["start_pin"] == {"component": "Q1", "pin": "bus_h"}
    assert pi["end_pin"] == {"component": "Q2", "pin": "bus_h"}
    assert spec["options"]["total_length"] == "5mm"
    assert spec["class"] == "RouteMeander"
    assert "from" not in spec
    assert "to" not in spec


def test_route_class_explicit_is_preserved():
    spec = _inflate_route({
        "name": "bus",
        "class": "RoutePathfinder",
        "from": "Q1.bus",
        "to": "Q2.bus",
    })
    assert spec["class"] == "RoutePathfinder"


def test_route_existing_pin_inputs_take_precedence():
    """显式写了 pin_inputs.start_pin 时 from 简记不应覆盖。"""
    spec = _inflate_route({
        "name": "bus",
        "from": "Q1.bus",
        "to": "Q2.bus",
        "options": {
            "pin_inputs": {
                "start_pin": {"component": "OVERRIDE", "pin": "x"}
            }
        }
    })
    pi = spec["options"]["pin_inputs"]
    assert pi["start_pin"] == {"component": "OVERRIDE", "pin": "x"}
    # to 的简记仍然把 end_pin 注入（因为没冲突）
    assert pi["end_pin"] == {"component": "Q2", "pin": "bus"}


def test_route_from_alone_raises():
    with pytest.raises(DesignDslError, match="同时提供"):
        _inflate_route({"name": "r", "from": "Q1.bus"})


def test_route_endpoint_without_dot_raises():
    with pytest.raises(DesignDslError, match="Component\\.pin"):
        _inflate_route({"name": "r", "from": "Q1bus", "to": "Q2.bus"})


def test_chip_size_string_form():
    sx, sy = dsl._parse_chip_size("10mm x 10mm")
    assert (sx, sy) == ("10mm", "10mm")


def test_chip_size_unicode_x_form():
    sx, sy = dsl._parse_chip_size("10mm × 8mm")
    assert (sx, sy) == ("10mm", "8mm")


def test_chip_size_dict_form():
    sx, sy = dsl._parse_chip_size({"size_x": "10mm", "size_y": "8mm"})
    assert (sx, sy) == ("10mm", "8mm")


def test_chip_size_list_form():
    sx, sy = dsl._parse_chip_size(["10mm", "8mm"])
    assert (sx, sy) == ("10mm", "8mm")


# ---------------------------------------------------------------------------
# 2. JSON Schema
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def schema():
    """加载 JSON schema；若 jsonschema 不可用整组 skip。"""
    pytest.importorskip("jsonschema")
    return json.loads(SCHEMA_FILE.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def validator(schema):
    from jsonschema import Draft7Validator
    Draft7Validator.check_schema(schema)
    return Draft7Validator(schema)


def test_schema_self_check(schema):
    from jsonschema import Draft7Validator
    Draft7Validator.check_schema(schema)


def test_example_yaml_conforms_to_schema(validator):
    doc = yaml.safe_load(EXAMPLE_YAML.read_text(encoding="utf-8"))
    errors = list(validator.iter_errors(doc))
    if errors:
        details = "\n".join(
            f"  at {list(e.absolute_path)}: {e.message}" for e in errors[:5])
        pytest.fail(f"示例 YAML 不通过 schema：\n{details}")


def test_schema_path_returns_existing_file_in_source_tree():
    pytest.importorskip("jsonschema")
    p = dsl.schema_path()
    assert p.exists(), f"schema file missing: {p}"
    # 必须紧贴 design_dsl.py，跟 wheel 一起被打包
    assert p.parent == Path(dsl.__file__).parent
    # 文件名带版本号便于将来 v2
    assert p.name == f"design_dsl_schema_v{dsl.CURRENT_DSL_VERSION}.json"


def test_validate_against_schema_passes_for_example():
    pytest.importorskip("jsonschema")
    doc = yaml.safe_load(EXAMPLE_YAML.read_text(encoding="utf-8"))
    errors = dsl.validate_against_schema(doc)
    assert errors == [], f"示例 YAML 不通过 schema：{errors}"


def test_validate_against_schema_collects_errors():
    pytest.importorskip("jsonschema")
    bad = {"design": {}, "components": "not a list"}
    errors = dsl.validate_against_schema(bad)
    assert len(errors) >= 2  # design.class 缺失 + components 不是 list
    joined = " | ".join(errors)
    assert "class" in joined
    assert "list" in joined or "array" in joined


@pytest.mark.parametrize("label,doc", [
    ("schema 前缀错误", {"schema": "foreign/2",
                    "design": {"class": "DesignPlanar"}}),
    ("缺 design", {"components": []}),
    ("design 缺 class", {"design": {"overwrite_enabled": True}}),
    ("componentSpec 多 $for", {
        "design": {"class": "DesignPlanar"},
        "components": [
            {"name": "Q", "class": "TransmonPocket", "$for": []}]}),
    ("componentSpec 未知键", {
        "design": {"class": "DesignPlanar"},
        "components": [
            {"name": "Q", "class": "TransmonPocket", "weird_key": 1}]}),
    ("class 既不在枚举也不是 dotted path", {
        "design": {"class": "DesignPlanar"},
        "components": [{"name": "Q", "class": "Nope"}]}),
    ("$for 空数组", {
        "design": {"class": "DesignPlanar"},
        "components": [
            {"$for": [], "name": "Q", "class": "TransmonPocket"}]}),
])
def test_schema_rejects_bad_doc(validator, label, doc):
    errors = list(validator.iter_errors(doc))
    assert errors, f"反例 '{label}' 应被 schema 抓到，却通过了"


# ---------------------------------------------------------------------------
# 3. 端到端：真实例化 4-qubit demo
# ---------------------------------------------------------------------------


def _design_planar_available():
    try:
        from qiskit_metal.designs.design_planar import DesignPlanar  # noqa: F401
    except Exception:
        return False
    return True


@pytest.mark.skipif(not _design_planar_available(),
                    reason="qiskit_metal designs not importable in this env")
def test_build_2x2_demo_creates_expected_components():
    import os
    os.environ.setdefault("QISKIT_METAL_HEADLESS", "1")

    design = dsl.build_design(EXAMPLE_YAML)

    assert design.__class__.__name__ == "DesignPlanar"
    assert dict(design.variables) == {"cpw_width": "12um", "cpw_gap": "7um"}
    assert design.chips.main.size.size_x == "10mm"
    assert design.chips.main.size.size_y == "10mm"

    component_names = sorted(design.components.keys())
    assert component_names == [
        "Q1", "Q2", "Q3", "Q4",
        "bottom_bus", "left_bus", "right_bus", "top_bus"]

    for qname in ("Q1", "Q2", "Q3", "Q4"):
        pins = set(design.components[qname].pins.keys())
        # transmon pocket 自带 a/b 默认 pin？只要包含我们声明的就行
        assert {"readout", "bus_h", "bus_v"}.issubset(pins)

    for rname in ("top_bus", "left_bus", "bottom_bus", "right_bus"):
        pins = set(design.components[rname].pins.keys())
        assert pins == {"start", "end"}
