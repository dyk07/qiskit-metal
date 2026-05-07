# -*- coding: utf-8 -*-
"""声明式 YAML DSL，用纯文本配置文件替代 Python 端的 design 构建脚本。

用法
====

最简调用：

    from qiskit_metal.toolbox_metal.design_dsl import build_design

    design = build_design("examples/dsl/2x2_4qubit.metal.yaml")

注册自定义组件：

    from qiskit_metal.toolbox_metal.design_dsl import register_component
    register_component("MyTransmon", MyTransmon)

得到的 ``design`` 是普通 ``QDesign``，可以继续在 Python 里追加组件、跑 GUI、
导出 GDS 等。本模块**不修改** ``import_export.py`` 的快照路径，两条路径互不干扰。

DSL 顶层结构
============

v1（兼容）结构：

::

        schema: qiskit-metal/design-dsl/1
        design:
            class: DesignPlanar         # 短名或完整 import 路径
            overwrite_enabled: true
            enable_renderers: true
            variables: {cpw_width: 12um, cpw_gap: 7um}
            chip:
                size: 10mm x 10mm         # 也可写 {size_x: 10mm, size_y: 10mm}
        vars: {qx: 1.55mm}            # 仅供 ${...} 插值，不进入 design.variables
        templates:                    # 可被 $extend 引用的复用块
            qubit:
                class: TransmonPocket
                options: {pad_width: 425um, ...}
        components:                   # 顺序实例化
            - {name: Q1, $extend: qubit, options: {pos_x: -${qx}}}
            - $for: [{name: Q2, x: 1mm}, {name: Q3, x: 2mm}]
                $extend: qubit
                name: ${name}
                options: {pos_x: ${x}}
        routes:                       # 默认 class=RouteMeander，from/to 简记自动展开
            - {name: bus, from: Q1.bus, to: Q2.bus, options: {total_length: 5mm}}

v2（Hamiltonian/Circuit/Netlist/Geometry 链）结构：

::

        schema: qiskit-metal/design-dsl/2
        vars:
            qx: 1.55mm                  # 全层共享插值变量
        hamiltonian:
            subsystems: {Q1: {EJ: 18GHz, EC: 250MHz}}
        circuit:
            Q1: {C: 65fF, L: 8nH}
        netlist:
            connections: [{from: Q1.bus, to: Q2.bus}]
        geometry:
            design: {class: DesignPlanar, chip: {size: 10mm x 10mm}}
            templates: {qubit: {class: TransmonPocket, options: {pad_width: 425um}}}
            components:
                - {name: Q1, $extend: qubit, options: {pos_x: -${qx}}}
            routes:
                - {name: bus, from: Q1.bus, to: Q2.bus, options: {total_length: 5mm}}

保留 key
========

- ``$extend``：从 ``templates`` 取一份模板与当前节点深合并。
- ``$for``：循环，列表元素是每轮的局部变量；本节点的其他兄弟键即为循环体。
- ``$include``：把另一份 YAML 文件的内容嵌入当前位置。
- ``$ref``：保留位（v1 未启用）。
- ``${name}``：字符串插值，按"循环局部变量 → vars → hamiltonian/circuit/netlist"优先级查找。
    支持点路径，如 ``${circuit.Q1.C}``。
"""

from __future__ import annotations

import importlib
import re
from pathlib import Path
from typing import Any, Callable, Mapping, Optional, Union

import yaml

__all__ = [
    "build_design",
    "register_component",
    "register_design",
    "clear_user_registry",
    "BUILTIN_COMPONENTS",
    "BUILTIN_DESIGNS",
    "DesignDslError",
]


# ---------------------------------------------------------------------------
# 注册表 —— 短名到完整 import 路径
# ---------------------------------------------------------------------------

BUILTIN_DESIGNS: dict[str, str] = {
    "DesignPlanar": "qiskit_metal.designs.design_planar.DesignPlanar",
    "DesignFlipChip": "qiskit_metal.designs.design_flipchip.DesignFlipChip",
    "DesignMultiPlanar":
        "qiskit_metal.designs.design_multiplanar.DesignMultiPlanar",
}

BUILTIN_COMPONENTS: dict[str, str] = {
    # qubits
    "TransmonPocket":
        "qiskit_metal.qlibrary.qubits.transmon_pocket.TransmonPocket",
    "TransmonPocketCL":
        "qiskit_metal.qlibrary.qubits.transmon_pocket_cl.TransmonPocketCL",
    "TransmonPocket6":
        "qiskit_metal.qlibrary.qubits.transmon_pocket_6.TransmonPocket6",
    "TransmonPocketTeeth":
        "qiskit_metal.qlibrary.qubits.transmon_pocket_teeth.TransmonPocketTeeth",
    "TransmonCross":
        "qiskit_metal.qlibrary.qubits.transmon_cross.TransmonCross",
    "TransmonCrossFL":
        "qiskit_metal.qlibrary.qubits.transmon_cross_fl.TransmonCrossFL",
    "TransmonConcentric":
        "qiskit_metal.qlibrary.qubits.transmon_concentric.TransmonConcentric",
    "TransmonInterdigitated":
        "qiskit_metal.qlibrary.qubits.Transmon_Interdigitated.TransmonInterdigitated",
    "StarQubit": "qiskit_metal.qlibrary.qubits.star_qubit.StarQubit",
    # tlines
    "RouteMeander": "qiskit_metal.qlibrary.tlines.meandered.RouteMeander",
    "RouteStraight": "qiskit_metal.qlibrary.tlines.straight_path.RouteStraight",
    "RouteAnchors": "qiskit_metal.qlibrary.tlines.anchored_path.RouteAnchors",
    "RoutePathfinder": "qiskit_metal.qlibrary.tlines.pathfinder.RoutePathfinder",
    "RouteMixed": "qiskit_metal.qlibrary.tlines.mixed_path.RouteMixed",
    "RouteFramed": "qiskit_metal.qlibrary.tlines.framed_path.RouteFramed",
    # terminations
    "OpenToGround":
        "qiskit_metal.qlibrary.terminations.open_to_ground.OpenToGround",
    "ShortToGround":
        "qiskit_metal.qlibrary.terminations.short_to_ground.ShortToGround",
    "LaunchpadWirebond":
        "qiskit_metal.qlibrary.terminations.launchpad_wb.LaunchpadWirebond",
    "LaunchpadWirebondCoupled":
        "qiskit_metal.qlibrary.terminations.launchpad_wb_coupled.LaunchpadWirebondCoupled",
    "LaunchpadWirebondDriven":
        "qiskit_metal.qlibrary.terminations.launchpad_wb_driven.LaunchpadWirebondDriven",
    # couplers
    "CoupledLineTee":
        "qiskit_metal.qlibrary.couplers.coupled_line_tee.CoupledLineTee",
    "LineTee": "qiskit_metal.qlibrary.couplers.line_tee.LineTee",
    "CapNInterdigitalTee":
        "qiskit_metal.qlibrary.couplers.cap_n_interdigital_tee.CapNInterdigitalTee",
    "TunableCoupler01":
        "qiskit_metal.qlibrary.couplers.tunable_coupler_01.TunableCoupler01",
    "TunableCoupler02":
        "qiskit_metal.qlibrary.couplers.tunable_coupler_02.TunableCoupler02",
}

_USER_COMPONENTS: dict[str, Any] = {}
_USER_DESIGNS: dict[str, Any] = {}


def register_component(short_name: str, cls_or_path: Union[type, str]) -> None:
    """把一个组件类（或完整 dotted path）注册到 DSL 短名空间。"""
    _USER_COMPONENTS[short_name] = cls_or_path


def register_design(short_name: str, cls_or_path: Union[type, str]) -> None:
    """把一个 QDesign 子类（或完整 dotted path）注册到 DSL 短名空间。"""
    _USER_DESIGNS[short_name] = cls_or_path


def clear_user_registry() -> None:
    """清空用户注册的组件/设计映射，便于在测试间隔离状态。"""
    _USER_COMPONENTS.clear()
    _USER_DESIGNS.clear()


# ---------------------------------------------------------------------------
# 异常
# ---------------------------------------------------------------------------


class DesignDslError(Exception):
    """DSL 解析或构建过程中的错误。"""


# ---------------------------------------------------------------------------
# 工具函数：deep merge / 类解析 / 字符串插值
# ---------------------------------------------------------------------------


def _deep_merge(base: Any, override: Any) -> Any:
    """递归深合并：dict ∩ dict 逐键合并，其他类型 override 直接覆盖 base。"""
    if isinstance(base, dict) and isinstance(override, dict):
        out = dict(base)
        for key, value in override.items():
            out[key] = _deep_merge(out.get(key), value) if key in out else value
        return out
    return override


def _resolve_class(name_or_path: str, table: Mapping[str, Any],
                   user_table: Mapping[str, Any], kind: str):
    """把短名或 dotted path 解析成实际类对象。

    短名优先级：用户注册表 → 内置注册表 → 把 ``name_or_path`` 当作 dotted path 直接 import。
    """
    if not isinstance(name_or_path, str) or not name_or_path:
        raise DesignDslError(f"{kind} class 必须是非空字符串，得到 {name_or_path!r}")

    target = user_table.get(name_or_path) or table.get(name_or_path) or name_or_path

    if not isinstance(target, str):
        return target  # 已经是类对象

    if "." not in target:
        raise DesignDslError(
            f"未知 {kind} 短名 '{name_or_path}'，可注册或写完整 dotted path")

    module_path, attr_name = target.rsplit(".", 1)
    try:
        module = importlib.import_module(module_path)
    except ImportError as exc:
        raise DesignDslError(
            f"无法 import {kind} 模块 '{module_path}': {exc}") from exc

    try:
        return getattr(module, attr_name)
    except AttributeError as exc:
        raise DesignDslError(
            f"模块 '{module_path}' 没有 {kind} 类 '{attr_name}'") from exc


_VAR_RE = re.compile(
    r"\$\{([a-zA-Z_][a-zA-Z0-9_]*(?:\.[a-zA-Z0-9_]+)*)\}")


def _resolve_path(ctx: Mapping[str, Any], path: str) -> Any:
    """从 ctx 里解析点路径（如 ``circuit.Q1.C``）。"""
    if path in ctx:
        return ctx[path]
    current: Any = ctx
    for part in path.split("."):
        if isinstance(current, Mapping) and part in current:
            current = current[part]
            continue
        if isinstance(current, list) and part.isdigit():
            index = int(part)
            try:
                current = current[index]
            except IndexError as exc:
                raise DesignDslError(
                    f"索引越界: ${{{path}}} -> {index}") from exc
            continue
        raise DesignDslError(
            f"未知 ${{{path}}}（可用顶层：{sorted(ctx)}）")
    return current


def _substitute_string(value: str, ctx: Mapping[str, Any]) -> str:
    """字符串内 ``${name}`` 替换为 ctx[name]；未知变量直接报错。"""

    def _repl(match: re.Match) -> str:
        name = match.group(1)
        return str(_resolve_path(ctx, name))

    return _VAR_RE.sub(_repl, value)


def _walk_substitute(node: Any, ctx: Mapping[str, Any]) -> Any:
    """递归遍历容器，对所有字符串叶子节点做 ``${var}`` 替换。"""
    if isinstance(node, dict):
        return {key: _walk_substitute(val, ctx) for key, val in node.items()}
    if isinstance(node, list):
        return [_walk_substitute(item, ctx) for item in node]
    if isinstance(node, str):
        return _substitute_string(node, ctx)
    return node


# ---------------------------------------------------------------------------
# YAML 加载与 $include 展开
# ---------------------------------------------------------------------------


def _load_yaml(source: Union[str, Path]) -> tuple[dict, Optional[Path]]:
    """支持文件路径（Path / 路径字符串）或直接传 YAML 文本。

    返回 (parsed_dict, base_dir)，base_dir 用来解析相对的 ``$include`` 路径。
    """
    if isinstance(source, Path):
        return _load_yaml_file(source)

    if isinstance(source, str):
        candidate = Path(source)
        if "\n" not in source and len(source) < 4096 and candidate.exists():
            return _load_yaml_file(candidate)
        try:
            data = yaml.safe_load(source)
        except yaml.YAMLError as exc:
            raise DesignDslError(f"YAML 解析失败：{exc}") from exc
        if not isinstance(data, dict):
            raise DesignDslError("DSL 顶层必须是 mapping")
        return data, None

    raise DesignDslError(
        f"build_design 接受 Path / str（路径或 YAML 文本），得到 {type(source).__name__}")


def _load_yaml_file(path: Path) -> tuple[dict, Path]:
    if not path.exists():
        raise DesignDslError(f"DSL 文件不存在：{path}")
    try:
        with path.open("r", encoding="utf-8") as handle:
            data = yaml.safe_load(handle)
    except yaml.YAMLError as exc:
        raise DesignDslError(f"YAML 解析失败 ({path})：{exc}") from exc
    if not isinstance(data, dict):
        raise DesignDslError(f"DSL 顶层必须是 mapping ({path})")
    return data, path.parent


def _expand_includes(node: Any, base_dir: Optional[Path]) -> Any:
    """递归处理 ``$include: relative/path.yaml``。"""
    if isinstance(node, dict):
        if set(node.keys()) == {"$include"}:
            include_path = node["$include"]
            if not isinstance(include_path, str):
                raise DesignDslError("$include 值必须是字符串路径")
            if base_dir is None:
                raise DesignDslError(
                    "调用方传入的是 YAML 文本而非文件路径，无法解析 $include")
            target = (base_dir / include_path).resolve()
            included, child_dir = _load_yaml_file(target)
            return _expand_includes(included, child_dir)
        return {key: _expand_includes(val, base_dir) for key, val in node.items()}
    if isinstance(node, list):
        return [_expand_includes(item, base_dir) for item in node]
    return node


def _extract_geometry_spec(spec: Mapping[str, Any]) -> Mapping[str, Any]:
    """允许 v2 把几何层放到 geometry 下，v1 仍直接在顶层。"""
    if "geometry" not in spec:
        return spec
    geometry = spec["geometry"]
    if not isinstance(geometry, dict):
        raise DesignDslError("geometry 必须是 mapping")
    return geometry


# ---------------------------------------------------------------------------
# 模板（$extend）与循环（$for）展开
# ---------------------------------------------------------------------------


def _resolve_template(name: str, templates: Mapping[str, Any],
                      seen: frozenset[str]) -> dict:
    """递归解析模板，把模板自身的 ``$extend`` 链路平展开来。"""
    if name in seen:
        chain = " -> ".join(list(seen) + [name])
        raise DesignDslError(f"$extend 出现循环：{chain}")
    if name not in templates:
        raise DesignDslError(
            f"未知模板 '{name}'（已知：{sorted(templates)}）")
    template = templates[name]
    if not isinstance(template, dict):
        raise DesignDslError(f"模板 '{name}' 必须是 mapping")
    if "$extend" in template:
        parent_name = template["$extend"]
        parent = _resolve_template(parent_name, templates, seen | {name})
        body = {key: val for key, val in template.items() if key != "$extend"}
        return _deep_merge(parent, body)
    return dict(template)


def _expand_node(node: Any, ctx: Mapping[str, Any],
                 templates: Mapping[str, Any]) -> list:
    """把任意节点展开为最终 spec 列表。

    - 普通节点：返回单元素列表 ``[处理后的节点]``
    - ``$for`` 节点：返回一组（每轮一份）
    """
    if not isinstance(node, dict):
        return [_walk_substitute(node, ctx)]

    if "$for" in node:
        iter_list = node["$for"]
        if not isinstance(iter_list, list):
            raise DesignDslError("$for 的值必须是列表")
        body = {key: val for key, val in node.items() if key != "$for"}
        results: list = []
        for index, iter_vars in enumerate(iter_list):
            if not isinstance(iter_vars, dict):
                raise DesignDslError(
                    f"$for[{index}] 必须是 mapping，得到 {type(iter_vars).__name__}")
            # 先用外层 ctx 把 iter_vars 自身的 ${...} 解析掉，避免循环体出现
            # "二次插值" 的需求 —— 比如 ``x: "-${qx}"`` 在循环体里被 ``${x}`` 引用时
            # 直接拿到的就是 "-1.55mm" 而不是 "-${qx}"。
            resolved_iter = _walk_substitute(iter_vars, ctx)
            new_ctx = {**ctx, **resolved_iter}
            results.extend(_expand_node(body, new_ctx, templates))
        return results

    if "$extend" in node:
        template_name = node["$extend"]
        if not isinstance(template_name, str):
            raise DesignDslError("$extend 的值必须是模板短名（字符串）")
        template = _resolve_template(template_name, templates, frozenset())
        body = {key: val for key, val in node.items() if key != "$extend"}
        merged = _deep_merge(template, body)
        return _expand_node(merged, ctx, templates)

    # 普通 dict：先做插值
    return [_walk_substitute(node, ctx)]


def _expand_list(items: list, ctx: Mapping[str, Any],
                 templates: Mapping[str, Any]) -> list:
    """把组件/路由列表逐项展开并 flatten。"""
    out: list = []
    for item in items:
        out.extend(_expand_node(item, ctx, templates))
    return out


def _apply_netlist_connections(design, netlist_spec: Mapping[str, Any]) -> None:
    """根据 netlist.connections 显式连接 pin。"""
    connections = netlist_spec.get("connections") or []
    if not connections:
        return
    if not isinstance(connections, list):
        raise DesignDslError("netlist.connections 必须是列表")
    for index, connection in enumerate(connections):
        if not isinstance(connection, dict):
            raise DesignDslError(
                f"netlist.connections[{index}] 必须是 mapping")
        from_ep = connection.get("from")
        to_ep = connection.get("to")
        if not from_ep or not to_ep:
            raise DesignDslError(
                f"netlist.connections[{index}] 需要 from/to")
        from_pin = _split_endpoint(from_ep, f"netlist.connections[{index}].from")
        to_pin = _split_endpoint(to_ep, f"netlist.connections[{index}].to")

        comp1_id = design.name_to_id.get(from_pin["component"])
        comp2_id = design.name_to_id.get(to_pin["component"])
        if comp1_id is None:
            raise DesignDslError(
                f"netlist 未找到组件 '{from_pin['component']}'")
        if comp2_id is None:
            raise DesignDslError(
                f"netlist 未找到组件 '{to_pin['component']}'")

        design.connect_pins(comp1_id, from_pin["pin"],
                            comp2_id, to_pin["pin"])


# ---------------------------------------------------------------------------
# 路由简记 from/to → pin_inputs
# ---------------------------------------------------------------------------


def _split_endpoint(endpoint: str, where: str) -> dict:
    """``"Q1.bus"`` → ``{"component": "Q1", "pin": "bus"}``"""
    if not isinstance(endpoint, str) or "." not in endpoint:
        raise DesignDslError(
            f"路由 {where} 必须形如 'Component.pin'，得到 {endpoint!r}")
    component, pin = endpoint.split(".", 1)
    component = component.strip()
    pin = pin.strip()
    if not component or not pin:
        raise DesignDslError(f"路由 {where} 的 component / pin 不能为空")
    return {"component": component, "pin": pin}


def _inflate_route(spec: dict) -> dict:
    """把 ``from`` / ``to`` 简记展开为 ``options.pin_inputs``。"""
    has_from = "from" in spec
    has_to = "to" in spec
    if not (has_from or has_to):
        return spec

    if not (has_from and has_to):
        raise DesignDslError(
            f"路由 '{spec.get('name', '?')}' 必须同时提供 from 与 to")

    options = dict(spec.get("options") or {})
    pin_inputs = dict(options.get("pin_inputs") or {})
    pin_inputs.setdefault("start_pin",
                          _split_endpoint(spec["from"], "from"))
    pin_inputs.setdefault("end_pin", _split_endpoint(spec["to"], "to"))
    options["pin_inputs"] = pin_inputs

    new_spec = {key: val for key, val in spec.items() if key not in ("from", "to")}
    new_spec["options"] = options
    new_spec.setdefault("class", "RouteMeander")
    return new_spec


# ---------------------------------------------------------------------------
# 设计 / 组件实例化
# ---------------------------------------------------------------------------


def _parse_chip_size(value: Any) -> tuple[Optional[str], Optional[str]]:
    """支持 ``"10mm x 10mm"`` / ``[10mm, 10mm]`` / ``{size_x, size_y}``。"""
    if isinstance(value, str):
        parts = re.split(r"\s*[xX×]\s*", value.strip())
        if len(parts) != 2:
            raise DesignDslError(
                f"chip.size 字符串需形如 '10mm x 10mm'，得到 {value!r}")
        return parts[0], parts[1]
    if isinstance(value, list):
        if len(value) != 2:
            raise DesignDslError("chip.size 列表必须是 [size_x, size_y]")
        return str(value[0]), str(value[1])
    if isinstance(value, dict):
        return value.get("size_x"), value.get("size_y")
    raise DesignDslError(f"无法识别的 chip.size：{value!r}")


def _instantiate_design(design_spec: Mapping[str, Any]):
    class_name = design_spec.get("class", "DesignPlanar")
    design_cls = _resolve_class(class_name, BUILTIN_DESIGNS, _USER_DESIGNS,
                                kind="design")

    init_kwargs: dict[str, Any] = {}
    if "metadata" in design_spec:
        init_kwargs["metadata"] = design_spec["metadata"]
    if "overwrite_enabled" in design_spec:
        init_kwargs["overwrite_enabled"] = bool(design_spec["overwrite_enabled"])
    if "enable_renderers" in design_spec:
        init_kwargs["enable_renderers"] = bool(design_spec["enable_renderers"])

    design = design_cls(**init_kwargs)

    for key, value in (design_spec.get("variables") or {}).items():
        design.variables[key] = value

    chip_spec = design_spec.get("chip")
    if chip_spec:
        chip_name = chip_spec.get("name", "main") if isinstance(chip_spec, dict) else "main"
        if chip_name not in design._chips:
            raise DesignDslError(f"design 中没有 chip '{chip_name}'")
        chip_size = design._chips[chip_name]["size"]

        if isinstance(chip_spec, dict) and "size" in chip_spec:
            size_x, size_y = _parse_chip_size(chip_spec["size"])
            if size_x is not None:
                chip_size["size_x"] = size_x
            if size_y is not None:
                chip_size["size_y"] = size_y

        if isinstance(chip_spec, dict):
            for key in ("size_x", "size_y", "size_z", "center_x", "center_y",
                        "center_z"):
                if key in chip_spec:
                    chip_size[key] = chip_spec[key]

    return design


def _instantiate_component(design, spec: Mapping[str, Any]) -> None:
    if "class" not in spec:
        raise DesignDslError(
            f"组件 spec 缺少 'class'：{spec.get('name', '?')}")
    if "name" not in spec:
        raise DesignDslError(f"组件 spec 缺少 'name'：{spec}")

    component_cls = _resolve_class(spec["class"], BUILTIN_COMPONENTS,
                                   _USER_COMPONENTS, kind="component")
    options = spec.get("options") or {}
    if not isinstance(options, dict):
        raise DesignDslError(
            f"组件 '{spec['name']}' 的 options 必须是 mapping")

    make = bool(spec.get("make", True))
    extra_kwargs = spec.get("init_kwargs") or {}

    component_cls(design, spec["name"], options=options, make=make,
                  **extra_kwargs)


# ---------------------------------------------------------------------------
# 顶层入口
# ---------------------------------------------------------------------------


def build_design(
    source: Union[str, Path],
    *,
    overrides: Optional[Mapping[str, Any]] = None,
    post_build: Optional[Callable[[Any], None]] = None,
):
    """从 YAML DSL 构建一个完整的 ``QDesign``。

    Args:
        source: YAML 文件路径，或直接的 YAML 文本。
        overrides: 顶层字段补丁，会与解析后的 spec 做深合并。常用于覆盖 ``vars``。
        post_build: 构建结束后调用，签名 ``f(design) -> None``。

    Returns:
        新建的 QDesign 实例（具体子类由 ``design.class`` 决定）。
    """
    spec, base_dir = _load_yaml(source)
    spec = _expand_includes(spec, base_dir)

    if overrides:
        spec = _deep_merge(spec, dict(overrides))

    schema = spec.get("schema")
    if schema is not None and not str(schema).startswith("qiskit-metal/design-dsl/"):
        raise DesignDslError(
            f"schema 字段不识别（期望 'qiskit-metal/design-dsl/<n>'）：{schema!r}")

    geometry_spec = _extract_geometry_spec(spec)
    if "design" not in geometry_spec:
        raise DesignDslError("DSL 顶层缺少 'design' 段")

    vars_table = dict(spec.get("vars") or {})
    if geometry_spec is not spec:
        vars_table = _deep_merge(vars_table, dict(geometry_spec.get("vars") or {}))

    circuit_spec = spec.get("circuit")
    hamiltonian_spec = spec.get("hamiltonian")
    netlist_spec = spec.get("netlist")

    resolved_circuit = (
        _walk_substitute(circuit_spec, vars_table) if circuit_spec else None)
    resolved_hamiltonian = (
        _walk_substitute(hamiltonian_spec,
                         {**vars_table, "circuit": resolved_circuit})
        if hamiltonian_spec else None)
    resolved_netlist = (
        _walk_substitute(netlist_spec,
                         {**vars_table, "circuit": resolved_circuit,
                          "hamiltonian": resolved_hamiltonian})
        if netlist_spec else None)

    ctx: dict[str, Any] = dict(vars_table)
    if resolved_circuit is not None:
        ctx["circuit"] = resolved_circuit
    if resolved_hamiltonian is not None:
        ctx["hamiltonian"] = resolved_hamiltonian
    if resolved_netlist is not None:
        ctx["netlist"] = resolved_netlist

    design_spec = geometry_spec["design"]
    if not isinstance(design_spec, dict):
        raise DesignDslError("design 段必须是 mapping")
    design_spec = _walk_substitute(design_spec, ctx)

    templates = dict(geometry_spec.get("templates") or {})

    design = _instantiate_design(design_spec)

    raw_components = geometry_spec.get("components") or []
    raw_routes = geometry_spec.get("routes") or []
    if not isinstance(raw_components, list):
        raise DesignDslError("'components' 必须是列表")
    if not isinstance(raw_routes, list):
        raise DesignDslError("'routes' 必须是列表")

    component_specs = _expand_list(raw_components, ctx, templates)
    route_specs = _expand_list(raw_routes, ctx, templates)

    for spec_item in component_specs:
        _instantiate_component(design, spec_item)
    for spec_item in route_specs:
        _instantiate_component(design, _inflate_route(spec_item))

    if resolved_netlist and isinstance(resolved_netlist, Mapping):
        _apply_netlist_connections(design, resolved_netlist)

    if any(value is not None for value in
           (resolved_hamiltonian, resolved_circuit, resolved_netlist)):
        design.metadata["dsl_chain"] = {
            "schema": schema,
            "vars": vars_table,
            "hamiltonian": resolved_hamiltonian,
            "circuit": resolved_circuit,
            "netlist": resolved_netlist,
            "geometry": {
                "design": design_spec,
                "templates": templates,
                "components": component_specs,
                "routes": route_specs,
            },
        }

    if post_build is not None:
        post_build(design)

    return design
