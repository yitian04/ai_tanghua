from __future__ import annotations

import socket
import struct
import subprocess
import time
from typing import Dict, List, Optional

from src.core.models import CommandResult, RobotStatus, Trajectory, TrajectoryPoint
from src.core.validation import validate_trajectory
from src.robot.base import RobotAdapter
from src.robot.ur5.urscript_builder import compile_urscript


RT_STRUCT_692 = struct.Struct(">d6d6d6d6d6d6d6d6d18d6d6d6dQ")
RT_STRUCT_540 = struct.Struct(">d6d6d6d6d6d6d6d6d18d")


class UR5RobotAdapter(RobotAdapter):
    """UR5 adapter using Dashboard, realtime port, and URScript sockets."""

    def __init__(self, dashboard_port: int = 29999, script_port: int = 30002, timeout: float = 5.0):
        self.ip_address = ""
        self.dashboard_port = dashboard_port
        self.script_port = script_port
        self.timeout = timeout
        self.last_dashboard_response = ""
        self.last_error = ""

    def set_ip(self, ip_address: str) -> None:
        self.ip_address = (ip_address or "").strip()

    def connect(self, ip_address: str) -> bool:
        self.set_ip(ip_address)
        return self.test_connection()["dashboard_ok"]

    def disconnect(self) -> bool:
        return True

    def is_connected(self) -> bool:
        return self.test_connection()["dashboard_ok"]

    def get_status(self) -> RobotStatus:
        info = self.get_robot_info()
        return RobotStatus(
            ok=bool(info.get("dashboard_ok")),
            connected=bool(info.get("dashboard_ok")),
            robot_mode=str(info.get("robot_mode", "unknown")),
            program_state=str(info.get("program_state", "unknown")),
            safety_status=str(info.get("safety_status", "unknown")),
            message=str(info.get("last_response", "")),
            data=info,
        )

    def check_ready(self) -> CommandResult:
        ready = self.check_motion_ready()
        return CommandResult(ok=bool(ready.get("ok")), message=ready.get("message", ""), data=ready)

    def stop(self) -> CommandResult:
        ok = self.stop_program()
        return CommandResult(ok=ok, message=self.last_dashboard_response or ("stopped" if ok else "stop failed"))

    def execute_trajectory(self, trajectory: Trajectory, output_pin: int = 0, **compile_options) -> CommandResult:
        errors = validate_trajectory(trajectory)
        if errors:
            return CommandResult(ok=False, message="; ".join(errors))

        ready = self.check_motion_ready()
        if not ready.get("ok"):
            return CommandResult(ok=False, message=ready.get("message", "robot not ready"), data=ready)

        script = compile_urscript(trajectory, output_pin=output_pin, **compile_options)
        if not self._send_script(script):
            self.set_discharge(False, output_pin=output_pin)
            return CommandResult(ok=False, message=f"URScript 发送失败：{self.last_error or self.last_dashboard_response}")
        return CommandResult(ok=True, message=f"URScript 已发送，轨迹点 {len(trajectory.points)} 个", data={"script": script})

    def ping_host(self, timeout_ms: int = 500) -> Dict:
        if not self.ip_address:
            return {"ok": False, "error": "missing robot ip", "output": ""}
        try:
            result = subprocess.run(
                ["ping", "-n", "1", "-w", str(int(timeout_ms)), self.ip_address],
                capture_output=True,
                timeout=max(1.0, timeout_ms / 1000.0 + 0.5),
            )
            output = (result.stdout + result.stderr).decode("gbk", errors="ignore")
            output_lower = output.lower()
            failure_markers = (
                "unreachable",
                "timed out",
                "could not find host",
                "general failure",
                "无法访问",
                "请求超时",
                "找不到主机",
                "传输失败",
                "一般故障",
            )
            ok = "ttl=" in output_lower and not any(marker in output_lower for marker in failure_markers)
            return {"ok": ok, "error": "" if ok else "ping failed", "output": output.strip()}
        except Exception as exc:
            return {"ok": False, "error": str(exc), "output": ""}

    def test_connection(self, timeout: Optional[float] = None) -> Dict:
        if not self.ip_address:
            return {"ok": False, "ping_ok": False, "dashboard_ok": False, "error": "missing robot ip", "greeting": "", "robotmode": ""}

        socket_timeout = self.timeout if timeout is None else float(timeout)
        ping_result = self.ping_host(timeout_ms=max(200, int(socket_timeout * 1000)))

        try:
            with socket.create_connection((self.ip_address, self.dashboard_port), timeout=socket_timeout) as sock:
                sock.settimeout(socket_timeout)
                greeting = self._read_line(sock)
                sock.sendall(b"robotmode\n")
                robotmode = self._read_line(sock)
            dashboard_ok = "robotmode" in robotmode.lower()
            self.last_dashboard_response = robotmode or greeting
            self.last_error = "" if dashboard_ok else f"unexpected dashboard response: {robotmode or greeting or 'empty'}"
            return {
                "ok": bool(ping_result.get("ok")) and dashboard_ok,
                "ping_ok": bool(ping_result.get("ok")),
                "ping_output": ping_result.get("output", ""),
                "dashboard_ok": dashboard_ok,
                "error": self.last_error,
                "greeting": greeting,
                "robotmode": robotmode,
            }
        except OSError as exc:
            self.last_error = str(exc)
            self.last_dashboard_response = str(exc)
            return {
                "ok": False,
                "ping_ok": bool(ping_result.get("ok")),
                "ping_output": ping_result.get("output", ""),
                "dashboard_ok": False,
                "error": str(exc),
                "greeting": "",
                "robotmode": "",
            }

    def power_on(self) -> bool:
        response = self._send_dashboard_command("power on")
        return self._response_ok(response, ("powering on", "power on", "ok"))

    def power_off(self) -> bool:
        response = self._send_dashboard_command("power off")
        return self._response_ok(response, ("powering off", "power off", "ok"))

    def brake_release(self) -> bool:
        response = self._send_dashboard_command("brake release")
        return self._response_ok(response, ("brake releasing", "brake released", "brake", "ok"))

    def stop_program(self) -> bool:
        response = self._send_dashboard_command("stop")
        return self._response_ok(response, ("stopped", "stopping", "ok"))

    def set_speed_fraction(self, fraction: float = 0.1) -> Dict:
        fraction = max(0.01, min(float(fraction), 1.0))
        response = self._send_dashboard_command(f"set speed {fraction:.3f}")
        ok = self._response_ok(response, ("setting speed", "speed", "ok"))
        return {"ok": ok, "response": response}

    def get_robot_mode(self) -> str:
        return self._send_dashboard_command("robotmode") or "unknown"

    def get_program_state(self) -> str:
        response = self._send_dashboard_command("programState")
        if not response:
            response = self._send_dashboard_command("programstate")
        return response or "unknown"

    def get_safety_status(self) -> str:
        response = self._send_dashboard_command("safetystatus")
        if not response:
            response = self._send_dashboard_command("safetymode")
        return response or "unknown"

    def get_robot_info(self) -> Dict:
        if not self.ip_address:
            return {
                "dashboard_ok": False,
                "ping_ok": False,
                "ip_address": "",
                "robot_mode": "missing ip",
                "program_state": "unknown",
                "safety_status": "unknown",
                "last_response": "missing robot ip",
            }

        test = self.test_connection()
        if not test["dashboard_ok"]:
            return {
                "dashboard_ok": False,
                "ping_ok": test.get("ping_ok", False),
                "ip_address": self.ip_address,
                "robot_mode": "unreachable",
                "program_state": "unknown",
                "safety_status": "unknown",
                "last_response": test["error"],
            }

        return {
            "dashboard_ok": True,
            "ping_ok": test.get("ping_ok", False),
            "ip_address": self.ip_address,
            "robot_mode": self.get_robot_mode(),
            "program_state": self.get_program_state(),
            "safety_status": self.get_safety_status(),
            "last_response": self.last_dashboard_response or test.get("robotmode", ""),
        }

    def check_motion_ready(self) -> Dict:
        info = self.get_robot_info()
        if not info.get("dashboard_ok"):
            return {"ok": False, "message": f"Dashboard 不可达：{info.get('last_response', '')}", "info": info}

        robot_mode = str(info.get("robot_mode", "")).lower()
        safety_status = str(info.get("safety_status", "")).lower()
        program_state = str(info.get("program_state", "")).lower()

        if "running" not in robot_mode:
            return {"ok": False, "message": f"机器人未处于可运动模式：{info.get('robot_mode')}", "info": info}
        if "normal" not in safety_status:
            return {"ok": False, "message": f"安全状态不允许运动：{info.get('safety_status')}", "info": info}
        if "playing" in program_state:
            return {"ok": False, "message": f"已有程序正在运行：{info.get('program_state')}", "info": info}

        realtime = self.get_realtime_state()
        if not realtime.get("ok"):
            return {"ok": False, "message": f"无法读取实时关节状态：{realtime.get('error')}", "info": info}

        return {"ok": True, "message": "机器人状态允许运动", "info": info, "realtime": realtime}

    def movej_degrees(
        self,
        target_degrees: List[float],
        speed_fraction: float = 0.1,
        velocity: float = 0.105,
        acceleration: float = 0.12,
        timeout_s: float = 120.0,
        tolerance_deg: float = 1.0,
    ) -> Dict:
        if len(target_degrees) != 6:
            return {"ok": False, "message": "目标关节角必须是 6 个值"}

        ready = self.check_motion_ready()
        if not ready.get("ok"):
            return ready

        speed_result = self.set_speed_fraction(speed_fraction)
        target_radians = [self._deg_to_rad(value) for value in target_degrees]
        target_literal = "[" + ", ".join(f"{value:.6f}" for value in target_radians) + "]"
        script = (
            "def slow_joint_move():\n"
            f"  movej({target_literal}, a={acceleration:.4f}, v={velocity:.4f})\n"
            "end\n"
            "slow_joint_move()"
        )

        if not self._send_script(script):
            return {"ok": False, "message": f"运动脚本发送失败：{self.last_error or self.last_dashboard_response}"}

        start = time.time()
        last_realtime = None
        while time.time() - start < timeout_s:
            time.sleep(0.5)
            realtime = self.get_realtime_state()
            if realtime.get("ok"):
                last_realtime = realtime
                joints = realtime.get("joint_degrees", [])
                if len(joints) == 6:
                    max_error = max(abs(current - target) for current, target in zip(joints, target_degrees))
                    if max_error <= tolerance_deg:
                        return {
                            "ok": True,
                            "message": f"已到达目标关节姿态，最大关节误差 {max_error:.2f}°",
                            "speed_response": speed_result.get("response", ""),
                            "realtime": realtime,
                        }

            program_state = self.get_program_state().lower()
            if "stopped" in program_state and last_realtime:
                joints = last_realtime.get("joint_degrees", [])
                if len(joints) == 6:
                    max_error = max(abs(current - target) for current, target in zip(joints, target_degrees))
                    if max_error <= tolerance_deg * 2:
                        return {
                            "ok": True,
                            "message": f"程序停止，关节已接近目标关节姿态，最大误差 {max_error:.2f}°",
                            "speed_response": speed_result.get("response", ""),
                            "realtime": last_realtime,
                        }

        return {"ok": False, "message": "等待关节运动完成超时，请检查机器人状态", "realtime": last_realtime}

    def get_realtime_state(self) -> Dict:
        if not self.ip_address:
            return {"ok": False, "error": "missing robot ip"}

        try:
            with socket.create_connection((self.ip_address, 30003), timeout=self.timeout) as sock:
                sock.settimeout(self.timeout)
                header = self._recv_exact(sock, 4)
                packet_size = struct.unpack(">i", header)[0]
                payload = self._recv_exact(sock, packet_size - 4)
        except OSError as exc:
            return {"ok": False, "error": str(exc)}

        try:
            if packet_size >= 692:
                values = RT_STRUCT_692.unpack(payload[:RT_STRUCT_692.size])
                tcp_pose = list(values[55:61])
            elif packet_size >= 540:
                values = RT_STRUCT_540.unpack(payload[:RT_STRUCT_540.size])
                tcp_pose = None
            else:
                return {"ok": False, "error": f"unsupported realtime packet size: {packet_size}"}

            q_actual = list(values[31:37])
            q_target = list(values[1:7])
            qd_actual = list(values[37:43])
            return {
                "ok": True,
                "packet_size": packet_size,
                "controller_time": float(values[0]),
                "joint_radians": q_actual,
                "joint_degrees": [self._rad_to_deg(value) for value in q_actual],
                "target_joint_degrees": [self._rad_to_deg(value) for value in q_target],
                "joint_speed_degrees": [self._rad_to_deg(value) for value in qd_actual],
                "tcp_pose_m": tcp_pose,
                "tcp_pose_mm_deg": self._tcp_to_mm_deg(tcp_pose) if tcp_pose else None,
            }
        except (struct.error, IndexError) as exc:
            return {"ok": False, "error": f"failed to parse realtime packet: {exc}"}

    def set_tool_output(self, pin: int, value: int) -> bool:
        if not 0 <= int(pin) <= 7:
            return False
        return self._send_script(f"set_digital_out({int(pin)}, {bool(value)})")

    def set_discharge(self, enabled: bool, output_pin: int = 0) -> bool:
        return self.set_tool_output(output_pin, 1 if enabled else 0)

    def execute_script(self, script: str) -> bool:
        return bool(script.strip()) and self._send_script(script)

    def compile_urscript(self, points: List[Dict] | List[TrajectoryPoint] | Trajectory, output_pin: int = 0, **options) -> str:
        return compile_urscript(self._coerce_trajectory(points), output_pin=output_pin, **options)

    def execute_path(self, points: List[Dict] | List[TrajectoryPoint] | Trajectory, output_pin: int = 0, **options) -> bool:
        return self.execute_trajectory(self._coerce_trajectory(points), output_pin=output_pin, **options).ok

    def _coerce_trajectory(self, points: List[Dict] | List[TrajectoryPoint] | Trajectory) -> Trajectory:
        if isinstance(points, Trajectory):
            return points
        converted = []
        for idx, point in enumerate(points):
            if isinstance(point, TrajectoryPoint):
                converted.append(point)
            else:
                converted.append(
                    TrajectoryPoint(
                        point_id=int(point.get("point_id", idx)),
                        curve_id=int(point.get("curve_id", 0)),
                        x_mm=float(point.get("x_mm", point.get("x", 0.0))),
                        y_mm=float(point.get("y_mm", point.get("y", 0.0))),
                        z_mm=float(point.get("z_mm", point.get("z", 0.0))),
                        speed_mm_s=float(point.get("speed_mm_s", point.get("speed", 50.0))),
                        drawing=bool(point.get("drawing", point.get("is_drawing", True))),
                        rx_deg=float(point.get("rx_deg", point.get("rx", point.get("tool_rx_deg", 0.0)))),
                        ry_deg=float(point.get("ry_deg", point.get("ry", point.get("tool_ry_deg", 180.0)))),
                        rz_deg=float(point.get("rz_deg", point.get("rz", point.get("tool_rz_deg", 0.0)))),
                    )
                )
        return Trajectory(points=converted)

    def _send_dashboard_command(self, command: str) -> str:
        if not self.ip_address:
            self.last_error = "missing robot ip"
            self.last_dashboard_response = self.last_error
            return ""
        try:
            with socket.create_connection((self.ip_address, self.dashboard_port), timeout=self.timeout) as sock:
                sock.settimeout(self.timeout)
                self._read_line(sock)
                sock.sendall((command.strip() + "\n").encode("utf-8"))
                time.sleep(0.1)
                response = self._read_line(sock)
            self.last_error = ""
            self.last_dashboard_response = response
            return response
        except OSError as exc:
            self.last_error = str(exc)
            self.last_dashboard_response = str(exc)
            return ""

    def _read_line(self, sock: socket.socket) -> str:
        chunks = []
        while True:
            try:
                data = sock.recv(4096)
                if not data:
                    break
                chunks.append(data)
                if b"\n" in data:
                    break
            except socket.timeout:
                break
        return b"".join(chunks).decode("utf-8", errors="ignore").strip()

    def _recv_exact(self, sock: socket.socket, size: int) -> bytes:
        chunks = []
        remaining = size
        while remaining > 0:
            chunk = sock.recv(remaining)
            if not chunk:
                raise OSError("connection closed while reading realtime data")
            chunks.append(chunk)
            remaining -= len(chunk)
        return b"".join(chunks)

    def _send_script(self, script: str) -> bool:
        if not self.ip_address:
            self.last_error = "missing robot ip"
            return False
        try:
            with socket.create_connection((self.ip_address, self.script_port), timeout=self.timeout) as sock:
                sock.settimeout(self.timeout)
                sock.sendall((script.rstrip() + "\n").encode("utf-8"))
            return True
        except OSError as exc:
            self.last_error = str(exc)
            self.last_dashboard_response = str(exc)
            return False

    @staticmethod
    def _rad_to_deg(value: float) -> float:
        return value * 180.0 / 3.141592653589793

    @staticmethod
    def _deg_to_rad(value: float) -> float:
        return value * 3.141592653589793 / 180.0

    @classmethod
    def _tcp_to_mm_deg(cls, tcp_pose: Optional[List[float]]) -> Optional[List[float]]:
        if not tcp_pose:
            return None
        xyz_mm = [value * 1000.0 for value in tcp_pose[:3]]
        rxyz_deg = [cls._rad_to_deg(value) for value in tcp_pose[3:6]]
        return xyz_mm + rxyz_deg

    @staticmethod
    def _response_ok(response: str, ok_markers) -> bool:
        if not response:
            return False
        lowered = response.lower()
        return any(marker in lowered for marker in ok_markers)


RobotController = UR5RobotAdapter
