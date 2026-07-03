"""
Python library to control an UR robot through its TCP/IP interface
Documentation from universal robots:
http://support.universal-robots.com/URRobot/RemoteAccess
"""
import sys
sys.path.append('C:\\Users\\13698\\Desktop\\yds-x\\MT_3c\\ur_robot_control')


import logging
from typing import List, Optional, Union
import urrtmon
import ursecmon
from scipy.spatial.transform import Rotation
import numpy as np
import yaml
from pathlib import Path
import math
import time

__author__ = "Olivier Roulet-Dubonnet"
__copyright__ = "Copyright 2011-2015, Sintef Raufoss Manufacturing"
__license__ = "LGPLv3"

def singleton(cls):
    _instance = {}

    def inner(*args, **kwargs):
        if cls not in _instance:
            _instance[cls] = cls(*args, **kwargs)
        return _instance[cls]
    return inner


class URRobot:
    """
    Python interface to socket interface of UR robot.
    programs are send to port 3002
    data is read from secondary interface(10Hz?) and real-time interface(125Hz) (called Matlab interface in documentation)
    Since parsing the RT interface uses som CPU, and does not support all robots versions, it is disabled by default
    The RT interfaces is only used for the get_force related methods
    Rmq: A program sent to the robot i executed immendiatly and any running program is stopped
    Python接口连接UR机器人的套接字接口。 程序通过3002端口发送给机器人。
    数据从次要接口（10Hz?）和实时接口（125Hz）（在文档中称为Matlab接口）读取。 由于解析实时接口需要一些CPU，
    并且不支持所有机器人版本，所以默认情况下是禁用的。 实时接口仅用于获取与力相关的方法。
    备注：发送给机器人的程序会立即执行，并且任何正在运行的程序都会被停止。
    """
    def __init__(self, host='192.168.3.111', use_rt=True):
        """
        URRobot类的__init__方法接收两个参数
        :param host: 机器人的IP地址或主机名，用于建立网络连接
        :param use_rt: 布尔值，决定是否使用实时连接。如果use_rt为True，那么将使用实时监视器来获取机器人的状态信息
        """
        self.move_params = ...
        self.limit = ...

        self.logger = logging.getLogger("urx")
        self.host = host
        self.csys = None  # 这行代码设置了csys属性为None。csys代表坐标系统（Coordinate System），但在这段代码中并没有明确的使用。

        '''
        次要监视器通过ursecmon.SecondaryMonitor(self.host)创建，其中self.host是机器人的IP地址或主机名。
        这个次要监视器会通过网络连接到机器人，并定期（例如每10Hz）从机器人获取状态数据。
        这些数据可能包括机器人的位置、速度、加速度、电流、电压、温度等信息。
        '''
        self.logger.debug("Opening secondary monitor socket")   # 这行代码记录了一条调试信息，表示正在打开次要监视器套接字
        self.secmon = ursecmon.SecondaryMonitor(self.host)  # data from robot at 10Hz

        self.rtmon = None  # 这行代码将rtmon属性设置为None。rtmon可能代表实时监视器（Real-Time Monitor），但在这段代码中并没有明确的使用。
        if use_rt:  # 如果use_rt为True，那么将使用实时监视器来获取机器人的状态信息
            self.rtmon = self.get_realtime_monitor()  # 这行代码调用了get_realtime_monitor方法，获取了一个实时监视器对象

        self.joinEpsilon = 0.01  # 这行代码将joinEpsilon属性设置为0.01。joinEpsilon可能代表关节精度，但在这段代码中并没有明确的使用。
        # 用于等待移动完成的关节移动的精度。
        # 这个值必须保守！否则我们可能会永远等待。
        # 这是在讨论机器人移动到指定位置时，如何确定移动是否完成。
        # 如果设置的精度过高，机器人可能永远无法达到这个精度，从而导致程序一直在等待。

        # 看起来URScript在接受浮点数的字符长度上有限制。这是在讨论URScript语言处理浮点数的能力，特别是在字符长度方面可能存在的限制
        self.max_float_length = 6  # FIXME: check max length!!! 这行代码将max_float_length属性设置为6。max_float_length可能代表浮点数的最大长度，但在这段代码中并没有明确的使用。
        self.secmon.wait()  # 这行代码调用了wait方法，等待次要监视器获取数据。这个方法会阻塞当前线程，直到次要监视器获取了数据。
        # 确保我们从机器人那里获取数据后，再让客户端访问我们的方法。
        self.set_digital_out(0, 1)
# ------------------------------------------  基础控制方法 ------------------------------------------
    def movej(self, joints, acc=0.1, vel=0.05, wait=True, relative=False, threshold=0.05) -> Optional[List[float]]:
        """
        movej 最快，是一个非线性移动方法，它会让机器人的每个关节独立移动到指定的位置。在URScript文档中有详细的说明。
        :param joints: 这是一个列表，包含了6个关节的目标位置
        :param acc: 这是加速度，用于控制机器人的运动 其单位是 "rad/s²"，即每秒钟转动的弧度数
        :param vel: 这是速度，用于控制机器人的运动 其单位是 "rad/s"，即每秒钟转动的弧度数
        :param wait: 这是一个布尔值，如果为True，那么程序将等待机器人到达目标位置后再返回
        :param relative: 这是一个布尔值，如果为True，那么程序将使用相对位置来控制机器人的运动
        :param threshold: 这是一个浮点数，用于控制机器人的运动。如果机器人的运动距离小于这个值，那么程序将认为机器人已经到达目标位置
        :return: 返回机器人的位置
        """
        if relative:  # 如果relative为True，那么程序将使用相对位置来控制机器人的运动
            line = self.getj()  # l是一个列表，包含了6个关节的当前位置
            joints = [v + line[i] for i, v in enumerate(joints)]  # 这行代码将joints列表中的每个元素与l列表中的对应元素相加
        prog = self._format_move("movej", joints, acc, vel)  # 这行代码调用了URRobot类的_format_move方法，用于生成一个URScript命令
        self.send_program(prog)  # 这行代码调用了URRobot类的send_program方法，将生成的URScript命令发送给机器人
        if wait:  # 如果wait为True，那么程序将等待机器人到达目标位置后再返回
            self._wait_for_move(joints[:6], threshold=threshold, joints=True)  # 这行代码调用了URRobot类的_wait_for_move方法，等待机器人到达目标位置
            return self.getj()  # 这行代码调用了URRobot类的getj方法，获取机器人的关节位置

    def movel(self, tpose, acc=0.1, vel=0.05, wait=True, relative=False, threshold=0.001) -> Optional[List[float]]:
        """
        movel是一个线性移动方法，工具中心点路径非常重要时，它会让机器人的末端执行器（TCP，Tool Center Point）沿着直线路径移动到指定的位置。
        :param tpose:  这是一个列表 基于机器人的末端执行器，包含了末端执行器的目标位置 偏移量单位是米(m)旋转角度Rx、Ry、Rz的单位是弧度(rad)
        :param acc: 这是加速度，用于控制机器人的运动 其单位是 "m/s²"，即每秒钟移动的米数
        :param vel: 这是速度，用于控制机器人的运动 其单位是 "m/s"，即每秒钟移动的米数
        :param wait: 这是一个布尔值，如果为True，那么程序将等待机器人到达目标位置后再返回
        :param relative:  这是一个布尔值，如果为True，那么程序将使用相对位置来控制机器人的运动
        :param threshold:  这是一个浮点数，用于控制机器人的运动。如果机器人的运动距离小于这个值，那么程序将认为机器人已经到达目标位置
        :return:返回机器人的位置
        """
        # 如果wait为True，那么程序将等待机器人到达目标位置后再返回
        return self.movex("movel", tpose, acc=acc, vel=vel, wait=wait, relative=relative, threshold=threshold)  # 发送移动命令

    def movep(self, tpose, acc=0.01, vel=0.01, wait=True, relative=False, threshold=0.05) -> Optional[List[float]]:
        """
        movep是一个路径移动方法，当工县中心点需要保持相同的速度经过多个路点时，使用末端等速运动规划指令。
        :param tpose: 这是一个列表 基于机器人的末端执行器，包含了末端执行器的目标位置 偏移量单位是米(m)旋转角度Rx、Ry、Rz的单位是弧度(rad)
        :param acc: 这是加速度，用于控制机器人的运动 其单位是 "m/s²"，即每秒钟移动的米数
        :param vel: 这是速度，用于控制机器人的运动 其单位是 "m/s"，即每秒钟移动的米数
        :param wait:   这是一个布尔值，如果为True，那么程序将等待机器人到达目标位置后再返回
        :param relative:    这是一个布尔值，如果为True，那么程序将使用相对位置来控制机器人的运动
        :param threshold:   这是一个浮点数，用于控制机器人的运动。如果机器人的运动距离小于这个值，那么程序将认为机器人已经到达目标位置
        :return:返回机器人的位置
        """
        return self.movex("movep", tpose, acc=acc, vel=vel, wait=wait, relative=relative, threshold=threshold)

    def movec(self, pose_via, pose_to, acc=0.01, vel=0.01, wait=True, threshold=0.05) -> Optional[List[float]]:
        """
        movec是一个圆弧移动方法，当工具中心点需要以固定速度进行圆形移动时 它会让机器人的末端执行器沿着圆弧路径移动到指定的位置。
        :param pose_via: 这是机器人末端执行器在圆弧路径上的中间点。机器人会首先移动到这个位置，然后再沿着圆弧路径移动到pose_to指定的位置。
        :param pose_to: 这是机器人末端执行器在圆弧路径上的终点。机器人会从pose_via指定的位置沿着圆弧路径移动到这个位置。
        :param acc: 这是加速度，用于控制机器人的运动 其单位是 "m/s²"，即每秒钟移动的米数
        :param vel: 这是速度，用于控制机器人的运动 其单位是 "m/s"，即每秒钟移动的米数
        :param wait: 这是一个布尔值，如果为True，那么程序将等待机器人到达目标位置后再返回
        :param threshold:  这是一个浮点数，用于控制机器人的运动。如果机器人的运动距离小于这个值，那么程序将认为机器人已经到达目标位置
        :return:返回机器人的位置
        """
        pose_via = [round(i, self.max_float_length) for i in pose_via]  # round用于对浮点数进行四舍五入 示例，print(round(3.14159, 2))
        pose_to = [round(i, self.max_float_length) for i in pose_to]
        prog = "movec(p%s, p%s, a=%s, v=%s, r=%s)" % (pose_via, pose_to, acc, vel, "0")
        self.send_program(prog)
        if wait:
            self._wait_for_move(pose_to, threshold=threshold)
            return self.getl()

    def _format_move(self, command, tpose, acc, vel, radius=0, prefix="") -> str:
        tpose = [round(i, self.max_float_length) for i in tpose]
        tpose.append(acc)
        tpose.append(vel)
        tpose.append(radius)
        return "{}({}[{},{},{},{},{},{}], a={}, v={}, r={})".format(command, prefix, *tpose)

    def movex(self, command, tpose, acc=0.01, vel=0.01, wait=True, relative=False, threshold=0.05) \
            -> Optional[List[float]]:
        """
        Send a move command to the robot. since UR robotene have several methods this one
        sends whatever is defined in 'command' string
        """
        if relative:
            l = self.getl()
            tpose = [v + l[i] for i, v in enumerate(tpose)]
        prog = self._format_move(command, tpose, acc, vel, prefix="p")
        self.send_program(prog)
        if wait:
            self._wait_for_move(tpose[:6], threshold=threshold)
            return self.getl()
        # if wait:
        #     while True :
        #         time.sleep(0.01)  
        #         if self.is_program_running()==False:
        #             break

    # def move_axis(self, axis='z', t=0, acc=0.1, vel=0.05, wait=True):
    #     """
    #     轴向运动
    #     t: 运动长度, 单位mm
    #     """
    #     def fun1(t, pose, n):
    #         t = t*1000
    #         rev = np.array([pose[3],pose[4],pose[5]])
    #         Rot=cv2.Rodrigues(rev)[0]
    #         rpy = np.array([0,0,0])
    #         rpyangles = cv2.RQDecomp3x3(Rot)[0]
    #         rpy[:] = rpyangles[:]
    #         rpy[n] = rpy[n] + t #+ 30
    #         rx = rpy[0]*math.pi/180.0;ry = rpy[1]*math.pi/180.0;rz = rpy[2]*math.pi/180.0
    #         #print(base_pose)
    #         rxsin = math.sin(rx); rxcos = math.cos(rx)
    #         rysin = math.sin(ry); rycos = math.cos(ry)
    #         rzsin = math.sin(rz); rzcos = math.cos(rz)
    #         Rotx = np.array([[1,0,0],[0,rxcos,-rxsin],[0,rxsin,rxcos]])
    #         Roty = np.array([[rycos,0,rysin],[0,1,0],[-rysin,0,rycos]])
    #         Rotz = np.array([[rzcos,-rzsin,0],[rzsin,rzcos,0],[0,0,1]])
    #         Rot = Rotz.dot(Roty.dot(Rotx))
    #         rv = cv2.Rodrigues(Rot)[0]
    #         pose[3] = rv[0][0]; pose[4] = rv[1][0]; pose[5] = rv[2][0]
    #         return pose
    #     t = t/1000
    #     pose0 = self.getl()
    #     pose = pose0
    #     if axis == 'x':
    #         pose[0] += t
    #     elif axis == 'y':
    #         pose[1] += t
    #     elif axis == 'z':
    #         pose[2] += t
    #     elif axis == 'a':
    #         pose[2] = t
    #     elif axis == 'r':
    #         pose = fun1(t, pose0, 2)
    #     elif axis == 'ry':
    #         pose = fun1(t, pose0, 1)
    #     elif axis == 'rx':
    #         pose = fun1(t, pose0, 0)
    #     self.movel(pose, acc, vel, wait)

    def move_rc(self, r=-0.04):
        """
        move_rc是一个圆弧移动方法，当工具中心点需要以固定速度进行圆形移动时 它会让机器人的末端执行器沿着圆弧路径移动到指定的位置。
        :param pose_via: 这是机器人末端执行器在圆弧路径上的中间点。机器人会首先移动到这个位置，然后再沿着圆弧路径移动到pose_to指定的位置。
        :param pose_to: 这是机器人末端执行器在圆弧路径上的终点。机器人会从pose_via指定的位置沿着圆弧路径移动到这个位置。
        :param acc: 这是加速度，用于控制机器人的运动 其单位是 "m/s²"，即每秒钟移动的米数
        :param vel: 这是速度，用于控制机器人的运动 其单位是 "m/s"，即每秒钟移动的米数
        :param num: 插值个数
        :param r: 圆弧半径  pose_via, pose_to, acc=0.01, vel=0.01, num=4, 
        """
        # pose_via_to 是 点pose_via 到 点pose_to 沿着半径为r的圆弧上进行插值得到的num个点（RZ也同步进行插值）
        # pose_via_to = [] 
        # for pose in pose_via_to:
        #     self.movel(pose, acc, vel, wait)
        tcp=[r,0,0,0,0,0]
        self.set_tcp(self, tcp)



    # def move_r_z(self, angle=0, z=0, acc=0.1, vel=0.05, wait=True):
    #     """
    #     旋转+Z轴向运动
    #     angle: 角度， 度
    #     z: 运动长度, 单位mm
    #     """
    #     pose = self.getl()
    #     rev = np.array([pose[3],pose[4],pose[5]])
    #     Rot=cv2.Rodrigues(rev)[0]
    #     rpy = np.array([0,0,0])
    #     rpyangles = cv2.RQDecomp3x3(Rot)[0]
    #     rpy[:] = rpyangles[:]
    #     rpy[2] = rpy[2] + angle #+ 30
    #     rx = rpy[0]*math.pi/180.0;ry = rpy[1]*math.pi/180.0;rz = rpy[2]*math.pi/180.0
    #     #print(base_pose)
    #     rxsin = math.sin(rx); rxcos = math.cos(rx)
    #     rysin = math.sin(ry); rycos = math.cos(ry)
    #     rzsin = math.sin(rz); rzcos = math.cos(rz)
    #     Rotx = np.array([[1,0,0],[0,rxcos,-rxsin],[0,rxsin,rxcos]])
    #     Roty = np.array([[rycos,0,rysin],[0,1,0],[-rysin,0,rycos]])
    #     Rotz = np.array([[rzcos,-rzsin,0],[rzsin,rzcos,0],[0,0,1]])
    #     Rot = Rotz.dot(Roty.dot(Rotx))
    #     rv = cv2.Rodrigues(Rot)[0]
    #     #print(rv,rpy)
    #     pose[3] = rv[0][0]; pose[4] = rv[1][0]; pose[5] = rv[2][0]
    #     pose[2] = pose[2] + z/1000
    #     self.movel(pose, acc, vel, wait)


    def tcp2base(self, p_tool) -> Optional[List[float]]:
        try:
            p_tool = np.array([*p_tool, 1])  # 将 p_tool 转换为齐次坐标
            tool_pose = self.getl()
            # 将欧拉角转换为旋转矩阵
            r = Rotation.from_euler('xyz', tool_pose[3:6], degrees=False)
            rotation_matrix = r.as_matrix()
            # 创建齐次变换矩阵
            transform_matrix = np.eye(4)
            transform_matrix[:3, :3] = rotation_matrix
            transform_matrix[:3, 3] = tool_pose[:3]
            p_base = np.dot(transform_matrix, p_tool)
            return p_base[:3]
        except Exception as e:
            self.logger.exception(e)

    def tool2base_transform(self, tool_pos, err_x=0, err_y=0, err_z=400):
        import cv2
        base_pos = self.getl()
        tpose = [0, 0, 0, 0, 0, 0]
        rev = np.array([base_pos[3], base_pos[4], base_pos[5]])
        Rot = cv2.Rodrigues(rev)[0]
        M_Rot = np.identity(4)                     # 末端转基底
        M_Rot[:3, :3] = Rot
        M_Rot[:3, 3] = np.array([base_pos[0]*1000, base_pos[1]*1000, base_pos[2]*1000])
        base_xyz = np.dot(M_Rot, tool_pos)

        tpose[0] = (base_xyz[0][0]+err_x)/1000.0
        tpose[1] = (base_xyz[1][0]+err_y)/1000.0
        tpose[2] = (err_z)/1000.0
        tpose[3:]=base_pos[3:]
        return tpose
    
    def selfmove_tool(self, tool_pos, err_x, err_y, err_z, angle=None, acc=0.1, vel=0.5,
                      wait=True, relative=False, threshold=None):
        """
        输入：末端坐标系下坐标
        移动到对应点位
        """
        import math 
        import cv2
        base_pos = self.getl()
        tpose = [0, 0, 0, 0, 0, 0]
        rev = np.array([base_pos[3], base_pos[4], base_pos[5]])
        Rot = cv2.Rodrigues(rev)[0]
        M_Rot = np.identity(4)  # 末端转基底
        M_Rot[:3, :3] = Rot
        M_Rot[:3, 3] = np.array([base_pos[0]*1000, base_pos[1]*1000, base_pos[2]*1000])
        base_xyz = np.dot(M_Rot, tool_pos)

        tpose[0] = (base_xyz[0][0]+err_x)/1000.0
        tpose[1] = (base_xyz[1][0]+err_y)/1000.0
        tpose[2] = (base_xyz[2][0]+err_z)/1000.0
        tpose[3:] = base_pos[3:]
        tpose[2] += 0.01
        # print('base:',base_xyz)
        if angle is not None:
            # print("angle",angle)
            # if angle >90:
            #     angle = angle - 90
            rpy = np.array([0, 0, 0])
            rpyangles = cv2.RQDecomp3x3(Rot)[0]
            rpy[:] = rpyangles[:]
            rpy[2] = rpy[2] + angle  # + 30
            rx = rpy[0]*math.pi/180.0; ry = rpy[1]*math.pi/180.0; rz = rpy[2]*math.pi/180.0
            # print(base_pose)
            rxsin = math.sin(rx); rxcos = math.cos(rx)
            rysin = math.sin(ry); rycos = math.cos(ry)
            rzsin = math.sin(rz); rzcos = math.cos(rz)
            Rotx = np.array([[1, 0, 0], [0, rxcos, -rxsin], [0, rxsin, rxcos]])
            Roty = np.array([[rycos, 0, rysin], [0, 1, 0], [-rysin, 0, rycos]])
            Rotz = np.array([[rzcos, -rzsin, 0], [rzsin, rzcos, 0], [0, 0, 1]])
            Rot = Rotz.dot(Roty.dot(Rotx))
            rv = cv2.Rodrigues(Rot)[0]
            # print(rv,rpy)
            tpose[3:] = rv[:]
            # print(tpose,rpy)
        print("tpose", tpose)
        return self.movex("movel", tpose, acc=acc, vel=vel, wait=wait, relative=relative, threshold=threshold)

# ------------------------------------------ 组合类方法 ------------------------------------------
    def movels(self, pose_list, acc=0.01, vel=0.01, radius=0.01, wait=True, threshold=0.05) -> Optional[List[float]]:
        """
        用于将多个movel命令连接起来，并应用一个混合半径
        :param pose_list: 每个元素都是一个表示位置的列表。这个列表中的元素按照顺序依次表示x、y、z的位置坐标和Rx、Ry、Rz的旋转角度
        :param acc:  加速度，用于控制机器人的运动 其单位是 "m/s²"，即每秒钟移动的米数
        :param vel:  速度，用于控制机器人的运动 其单位是 "m/s"，即每秒钟移动的米数
        :param radius: 混合半径，用于在机器人移动到每个位置时进行平滑过渡，以避免机器人在移动过程中突然停止或改变方向。其单位是米(m)
        :param wait: 如果为True，那么程序将等待机器人到达目标位置后再返回
        :param threshold:  用于控制机器人的运动。如果机器人的运动距离小于这个值，那么程序将认为机器人已经到达目标位置
        :return: 返回机器人的位置
        """
        return self.movexs("movel", pose_list, acc, vel, radius, wait, threshold=threshold)

    def movexs(self, command, pose_list, acc=0.01, vel=0.01, radius=0.01, wait=True, threshold=0.05) \
            -> Optional[List[float]]:
        """
        Concatenate several movex commands and applies a blending radius
        pose_list is a list of pose.
        This method is usefull since any new command from python
        to robot make the robot stop
        """
        header = "def myProg():\n"
        end = "end\n"
        prog = header
        for idx, pose in enumerate(pose_list):
            if idx == (len(pose_list) - 1):
                radius = 0
            prog += self._format_move(command, pose, acc, vel, radius, prefix="p") + "\n"
        prog += end
        self.send_program(prog)
        if wait:
            self._wait_for_move(target=pose_list[-1], threshold=threshold)
            return self.getl()

# ------------------------------------------  设置机器人状态 ------------------------------------------
    def close(self) -> None:
        """
        断开连接，并停止
        :return:
        """
        self.logger.info("Closing sockets to robot")
        self.secmon.close()
        if self.rtmon:
            self.rtmon.stop()

    def set_tcp(self, tcp) -> None:
        """
        设置机器人末端执行器（Tool Center Point，TCP）的位置和旋转角度
        :param tcp: 。tcp参数是一个包含6个元素的列表，前三个元素是末端执行器的位置，后三个元素是末端执行器的旋转角度。
        :return: 无返回值
        """
        prog = "set_tcp(p[{}, {}, {}, {}, {}, {}])".format(*tcp)
        self.send_program(prog)

    def set_payload(self, weight, cog=None) -> None:
        """
        设置机器人的负载
        :param weight: 负载的重量，单位是千克(kg)
        :param cog: 负载的重心位置，如果没有指定，那么就使用工具中心点（TCP）作为负载的重心位置
        :return: 无返回值
        """
        if cog:
            cog = list(cog)
            cog.insert(0, weight)
            prog = "set_payload({}, ({},{},{}))".format(*cog)
        else:
            prog = "set_payload(%s)" % weight
        self.send_program(prog)

    def set_gravity(self, vector=None) -> None:
        """
        设置重力的方向
        :param vector: 一个包含3个元素的列表，表示重力的方向，例如[0, 0, -9.82]
        :return: 无返回值
        """
        if vector is None:
            vector = [0, 0, -9.82]
        prog = "set_gravity(%s)" % list(vector)
        self.send_program(prog)

    def set_digital_out(self, output, val) -> None:
        """
        设置数字输出
        :param output: 输出端口的编号
        :param val: 输出的值，可以是 True 或 False
        :return: 无返回值
        """
        if val in (True, 1):
            val = "True"
        else:
            val = "False"
        self.send_program('digital_out[%s]=%s' % (output, val))

    def set_analog_out(self, output, val) -> None:
        """
        设置模拟输出
        :param output: 输出端口的编号
        :param val: 输出的值，可以是 0 到 1 之间的浮点数，表示输出电压的百分比
        :return: 无返回值
        """
        prog = "set_analog_out(%s, %s)" % (output, val)
        self.send_program(prog)

    def set_tool_voltage(self, val) -> None:
        """
        设置工具电压,为机器人工具（例如夹具、焊枪等）提供电力的。通过调用这个函数并传入适当的电压值，可以控制机器人工具的工作状态。
        :param val: 电压值，可以是 0、12 或 24
        :return: 无返回值
        """
        prog = "set_tool_voltage(%s)" % val
        self.send_program(prog)

    def set_freedrive(self, val, timeout=60) -> None:
        """
        设置机器人的自由驱动模式
        :param val: 为True，机器人进入人手示教模式。为False，机器人退出人手示教模式
        :param timeout: 默认60s， 如果没有任何操作，默认机器人将在60秒后自动退出人手示教模式
        :return: 无返回值
        """
        if val:
            self.send_program("def myProg():\n\tfreedrive_mode()\n\tsleep({})\nend".format(timeout))
        else:
            # This is a non-existant program, but running it will stop freedrive
            self.send_program("def myProg():\n\tend_freedrive_mode()\nend")

    def set_simulation(self, val) -> None:
        """
        设置机器人的模拟模式
        :param val: 为True，进入模拟模式
        :return: 无返回值
        """
        if val:
            self.send_program("set sim")
        else:
            self.send_program("set real")

# ------------------------------------------ 读取机器人状态 ------------------------------------------
    def is_program_running(self) -> bool:
        """
        检查程序是否正在运行。
        警告！: 在发送程序之后，机器人可能需要几十分之一秒的时间才能进入运行状态
        :return: bool, 如果程序正在运行，返回True；否则返回False
        """
        return self.secmon.is_program_running()

    def is_running(self) -> bool:
        """
        判断机器人是否正在运行
        :return:返回 True
        """
        return self.secmon.running

    def getl(self, wait=True, _log=True) -> Optional[List[float]]:
        """
        获取TCP姿态
        :param wait: 如果为True，那么这个方法会阻塞当前线程，直到从机器人获取到新的数据。如果为False，那么这个方法会立即返回最近一次从机器人获取的数据。
        "X"：末端执行器在x轴上的位置，单位是米(m)。
        "Y"：末端执行器在y轴上的位置，单位是米(m)。
        "Z"：末端执行器在z轴上的位置，单位是米(m)。
        "Rx"：末端执行器绕x轴的旋转角度，单位是弧度(rad)。
        "Ry"：末端执行器绕y轴的旋转角度，单位是弧度(rad)。
        "Rz"：末端执行器绕z轴的旋转角度，单位是弧度(rad)。
        :param _log:
        :return:
        """
        pose = self.secmon.get_cartesian_info(wait)
        if pose:
            pose = [pose["X"], pose["Y"], pose["Z"], pose["Rx"], pose["Ry"], pose["Rz"]]
        if _log:
            self.logger.debug("Received pose from robot: %s", pose)
        return pose

    def getj(self, wait=False) -> List[float]:
        """
        获取关节姿态
        :param wait: 如果wait为True，阻塞当前线程，直到从机器人获取到新的数据。如果为False，那么这个方法会立即返回最近一次从机器人获取的数据。
        :return: 列表，包含了6个关节的位置
        """
        jts = self.secmon.get_joint_data(wait)  # 字典格式，获取关节数据
        return [jts["q_actual0"], jts["q_actual1"], jts["q_actual2"], jts["q_actual3"], jts["q_actual4"],
                jts["q_actual5"]]

    def get_realtime_monitor(self):
        """
        返回一个指向实时监控对象的指针，获取实时监控对象。
        用于调用urrtmon类的函数。 self.rtmon.tcf_pose()d等
        :return: self.rtmon
        """
        if not self.rtmon:
            self.logger.info("Opening real-time monitor socket")
            self.rtmon = urrtmon.URRTMonitor(self.host)  # som information is only available on rt interface
            self.rtmon.start()
        self.rtmon.set_csys(self.csys)
        return self.rtmon

    # --------------------- 添加函数 -------------------------------
    def joint_target(self, wait=False) -> List[float]: # 使用这个函数获取关节位置
        """ Get the actual joint current."""
        return self.rtmon.joint_target(wait)

    def joint_actual(self, wait=False) -> List[float]:
        return self.rtmon.joint_actual(wait)

    def tcp_actual(self, wait=False) -> List[float]:  # 使用这个函数获取位置
        """ Get the actual tcp target."""
        return self.rtmon.tcp_actual(wait)

    def tcp_speed(self, wait=False) -> List[float]:  # 使用这个函数获取速度
        """ Get the actual tcp speed."""
        return self.rtmon.tcp_speed(wait)

    def tcp_target_speed(self, wait=False) -> List[float]:
        """ Get the actual tcp accele."""
        return self.rtmon.tcp_target_speed(wait)

    def tcp_accele(self, wait=False) -> List[float]:
        """ Get the actual tcp accele."""
        return self.rtmon.tcp_accele(wait)
    # ----------------------------------------------------------------

    def get_tcp_force(self, wait=True) -> List[float]:
        """
        返回TCP（工具中心点）处测量的力矢量，可以用于了解机器人在执行动作时所受到的力和扭矩，
        这对于某些需要精确控制力的应用（例如装配、打磨、抛光等）非常有用
        :param wait: 如果wait为True，这个函数会阻塞，将在返回之前等待下一个数据包
        :return: 在TCP处测量的力和扭矩，单位是牛顿和牛顿米。返回一个包含6个元素的列表，分别表示X、Y、Z方向的力和扭矩
        """
        return self.rtmon.getTCFForce(wait)  # 调用urrtmon.py文件的方法

    # 有用的方法
    def get_force(self, wait=True) -> float:
        """
        机器人在执行动作时所受到的力的大小
        :param wait: 调用get_tcp_force()函数，如果wait为True，这个函数会阻塞，将在返回之前等待下一个数据包
            F = sqrt(x^2 + y^2 + z^2)
        :return: 力的大小
        """
        tcpf = self.get_tcp_force(wait)
        force = 0
        for i in tcpf:
            force += i ** 2  # i ** 2 是对变量 i 进行平方运算
        return force ** 0.5

    def _get_dist(self, target, joints=False) -> float:
        """
        计算机器人当前位置与目标位置之间的距离
        :param target:  目标位置, 一个包含6个元素的列表
        :param joints:  如果为True，那么计算机器人当前关节位置与目标关节位置之间的距离
        :return: float: 机器人当前位置与目标位置之间的距离
        """
        if joints:
            return self._get_joints_dist(target)
        else:
            return self._get_lin_dist(target)

    def _get_lin_dist(self, target) -> float:
        """
        计算机器人当前位置与目标位置之间的距离
        :param target:  目标位置, 一个包含6个元素的列表，前三个元素是位置坐标，后三个元素是旋转角度
        :return: float: 机器人当前位置与目标位置之间的距离
        """
        # FIXME: we have an issue here, it seems sometimes the axis angle received from robot
        pose = self.getl(wait=True)
        dist = 0
        for i in range(3):
            dist += (target[i] - pose[i]) ** 2
        for i in range(3, 6):
            dist += ((target[i] - pose[i]) / 5) ** 2  # arbitraty length like
        return dist ** 0.5

    def _get_joints_dist(self, target) -> float:
        """
        计算机器人当前关节位置与目标关节位置之间的距离（欧氏距离）
        评估机器人的当前位置与目标位置的接近程度
        :param target:  目标位置, 一个包含6个元素的列表
        :return: float 机器人当前关节位置与目标关节位置之间的距离
        """
        joints = self.getj(wait=True)  # 获取关节姿态
        dist = 0
        for i in range(6):
            dist += (target[i] - joints[i]) ** 2  # 计算机器人当前关节位置与目标关节位置之间的距离
        return dist ** 0.5

    def get_analog_inputs(self) -> List[float]:
        """
         获取所有模拟输入
        :return:float列表,其中的每个元素代表一个模拟输入端口的值
        """
        return self.secmon.get_analog_inputs()

    def get_analog_in(self, nb, wait=False) -> List[float]:
        """
        获取所有模拟输入,模拟输入通常用于接收来自各种传感器的信号
        :param nb: 模拟输入端口的编号
        :param wait: 如果wait为True，这个函数会阻塞，将在返回之前等待下一个数据包
        :return: float:模拟输入端口的值
        """
        return self.secmon.get_analog_in(nb, wait=wait)

    # TODO
    def get_digital_in_bits(self) -> int:
        """
        用于获取机器人的数字输入状态。这个方法返回一个整数，其中每一位代表一个对应的数字输入的状态。
        :return:如果某一位被设置为1，那么表示对应的数字输入为高电平。如果某一位被设置为0，那么表示对应的数字输入为低电平.
        """
        return self.secmon.get_digital_in_bits()

    # TODO
    def get_digital_in(self, nb, wait=False):
        """

        :param nb:
        :param wait:
        :return:
        """
        return self.secmon.get_digital_in(nb, wait)

    # TODO
    def get_digital_out(self, val, wait=False):
        """

        :param val:
        :param wait:
        :return:
        """
        return self.secmon.get_digital_out(val, wait=wait)

    # TODO
    def get_digital_out_bits(self, wait=False):
        """

        :param wait:
        :return:
        """
        return self.secmon.get_digital_out_bits(wait=wait)

# ------------------------------------------  通用函数 ------------------------------------------
    def __repr__(self):
        """
        用于定义一个对象的“官方”字符串表示。
        当打印一个对象或者使用repr()函数时，Python会调用这个方法。
        在代码中，__repr__方法返回一个字符串，表示机器人对象的IP地址和状态。
        :return:
        """
        return "Robot Object (IP=%s, state=%s)" % (self.host, self.secmon.get_all_data()["RobotModeData"])

    def __str__(self):
        """
        用于定义一个对象的“非正式”或者可读性好的字符串表示。
        当使用print()函数或者str()函数时，Python会调用这个方法。
        在代码中，__str__方法直接返回__repr__方法的结果。
        :return:
        """
        return self.__repr__()

    def __enter__(self):
        """
        用于实现Python的上下文管理协议的。当你使用with语句时，Python会调用__enter__方法，并在with语句结束时调用__exit__方法
        :return:
        """
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        """
        用于实现Python的上下文管理协议的。当你使用with语句时，Python会调用__enter__方法，并在with语句结束时调用__exit__方法
        :param exc_type:
        :param exc_value:
        :param traceback:
        :return:
        """
        self.close()

    def stopl(self, acc=0.5):
        self.send_program("stopl(%s)" % acc)

    def stopj(self, acc=1.5):
        self.send_program("stopj(%s)" % acc)

    def stop(self):
        self.stopj()

    def send_program(self, prog) -> None:
        """
        它用于向机器人发送一个完整的程序。这个程序是用URScript（Universal Robots脚本）编写的。
        :param prog: 字符串, "命令(参数1， 参数2， 参数3， ...)"
        :return: 无返回值
        """
        self.logger.info("Sending program: " + prog)
        self.secmon.send_program(prog)

    def send_message(self, msg):
        """
        向机器人控制器上的 GUI 日志选项卡发送消息
        :param msg: 示例，robot.send_message("The robot is starting to move.")
        :return:
        """
        prog = "textmsg(%s)" % msg
        self.send_program(prog)

# ------------------------------------------ fixme ---------------------------------------------
    # FIXME：可能需要修改
    def _wait_for_move(self, target, threshold=None, timeout=5, joints=False):
        """
        wait for a move to complete. Unfortunately there is no good way to know when a move has finished
        so for every received data from robot we compute a dist equivalent and when it is lower than
        'threshold' we return.
        if threshold is not reached within timeout, an exception is raised
        等待下一步完成。
        不幸的是，没有一个好的方法来知道什么时候一个移动已经完成，
        因此，对于每一个从机器人接收到的数据，我们计算一个等价的距离，当它低于“阈值”时，我们返回。如果在超时内未达到阈值，则引发异常
        """
        self.logger.debug("Waiting for move completion using threshold %s and target %s", threshold, target)
        start_dist = self._get_dist(target, joints)
        if threshold is None:
            threshold = start_dist * 0.2
            if threshold < 0.001:  # roboten precision is limited
                threshold = 0.001
            self.logger.debug("No threshold set, setting it to %s", threshold)
        count = 0
        while True:
            if not self.is_running():
                return
                # raise RobotException("Robot stopped")
            dist = self._get_dist(target, joints)
            self.logger.debug("distance to target is: %s, target dist is %s", dist, threshold)
            if not self.secmon.is_program_running():
                if dist < threshold:
                    self.logger.debug("we are threshold(%s) close to target, move has ended", threshold)
                    return
                count += 1
                if count > timeout * 10:
                    raise Exception("Goal not reached but no program has been running for {} seconds. dist is {}, threshold is {}, target is {}, current pose is {}".format(timeout, dist, threshold, target, self.getl()))
            else:
                count = 0

    def speedx(self, command, velocities, acc, min_time):
        vels = [round(i, self.max_float_length) for i in velocities]
        vels.append(acc)
        vels.append(min_time)
        prog = "{}([{},{},{},{},{},{}], a={}, t_min={})".format(command, *vels)
        self.send_program(prog)

    def servoc(self, tpose, acc=0.01, vel=0.01, wait=True, relative=False, threshold=None):
        """
        Send a servoc command to the robot. See URScript documentation.
        """
        return self.movex("servoc", tpose, acc=acc, vel=vel, wait=wait, relative=relative, threshold=threshold)

    # HACK
    def translate(self, vect, acc=0.01, vel=0.01, wait=True, command="movel"):
        """
        move tool in base coordinate, keeping orientation
        """
        p = self.getl()
        p[0] += vect[0]
        p[1] += vect[1]
        p[2] += vect[2]
        return self.movex(command, p, vel=vel, acc=acc, wait=wait)

    # HACK
    def up(self, z=0.05, acc=0.01, vel=0.01):
        """
        Move up in csys z
        """
        p = self.getl()
        p[2] += z
        self.movel(p, acc=acc, vel=vel)

    # HACK
    def down(self, z=0.05, acc=0.01, vel=0.01):
        """
        Move down in csys z
        """
        self.up(-z, acc, vel)
    def move_r_z(self, angle=0, z=0, acc=0.1, vel=0.05, wait=True):
        """
        旋转+Z轴向运动
        angle: 角度， 度
        z: 运动长度, 单位mm
        """
        base_pos = self.getl()
        angle_degrees = angle
        original_vector = np.array([base_pos[3], base_pos[4], base_pos[5]])
        # RZ
        axis = [0, 0, 1]
        # 将原始旋转矢量转换为四元数
        original_rotation = Rotation.from_rotvec(original_vector)
        # 计算额外的旋转四元数
        angle_radians = np.radians(angle_degrees)
        additional_rotation = Rotation.from_rotvec(angle_radians * np.array(axis))
        # 应用额外的旋转到原始旋转上
        new_rotation = additional_rotation * original_rotation
        # 将结果四元数转换回旋转矢量
        new_rotation_vector = new_rotation.as_rotvec()
        base_pos[3] = new_rotation_vector[0];base_pos[4] = new_rotation_vector[1];base_pos[5] = new_rotation_vector[2]
        base_pos[2] += z/1000
        self.movel(base_pos, acc, vel, wait)

    def move_axis(self, axis='z', axis_angle = 0, t=0, acc=0.1, vel=0.05, wait=True):

        def rotate_vector(t, base_pos, axis):
            """
            轴向运动
            t: 运动长度, 单位mm
            """
            angle_degrees = t*1000
            original_vector = np.array([base_pos[3], base_pos[4], base_pos[5]])
            if axis == 'rx':
                axis = [1, 0, 0]
            elif axis == 'ry':
                axis = [0, 1, 0]
            elif axis == 'rz':
                axis = [0, 0, 1]
            # 将原始旋转矢量转换为四元数
            original_rotation = Rotation.from_rotvec(original_vector)
            # 计算额外的旋转四元数
            angle_radians = np.radians(angle_degrees)
            additional_rotation = Rotation.from_rotvec(angle_radians * np.array(axis))
            # 应用额外的旋转到原始旋转上
            new_rotation = additional_rotation * original_rotation
            # 将结果四元数转换回旋转矢量
            new_rotation_vector = new_rotation.as_rotvec()
            base_pos[3] = new_rotation_vector[0];base_pos[4] = new_rotation_vector[1];base_pos[5] = new_rotation_vector[2]
            return base_pos
        t = t/1000
        pose0 = self.getl()
        pose = pose0
        if axis == 'x':
            pose[0] += t
        elif axis == 'y':
            pose[1] += t
        elif axis == 'z':
            pose[2] += t
        elif axis == 'a':
            pose[2] = t
        elif axis == 'angle':
            pose[0] += t * math.cos(math.radians(axis_angle))
            pose[1] += t * math.sin(math.radians(axis_angle))
        elif axis == 'rx':
            pose = rotate_vector(t, pose, axis)
        elif axis == 'ry':
            pose = rotate_vector(t, pose, axis)
        elif axis == 'rz':
            pose = rotate_vector(t, pose, axis)
        self.movel(pose, acc, vel, wait)

def create_robot():
    filename = Path(__file__).parent / "robot_config.yaml"
    with open(filename, 'r', encoding='utf-8') as f:
        robot_config = yaml.safe_load(f)

    # 创建URRobot实例
    robot_s = {}
    robot_name = []
    grap = None
    for name, config in robot_config.items():
        host = config['host']
        use_rt = config['use_rt']
        gripper = config['gripper']
        tcp = config['tcp']
        payload = config['payload']
        gravity = config['gravity']

        robot = URRobot(host, use_rt)
        robot.move_params = config['move_params']
        robot.limit = config['limit']
        # 设置参数
        robot.set_tcp(tcp)  # 工具中心点
        robot.set_payload(payload['pyload_weight'], payload['payload_cog'])  # 负载
        robot.set_gravity(gravity)  # 设置重力
        robot_s[name] = robot
        robot_name.append(name)


    return robot_s, robot_name, grap


if __name__ == '__main__':
    test_robot = URRobot(host='192.168.3.111', use_rt=True)
    time.sleep(3)
    test_robot.move_axis(axis='z',t=-5, acc=0.1, vel=0.05)