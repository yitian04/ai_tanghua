"""Controller-resident watchdog and explicitly taught entry/exit movements."""
import math
from .path_config import validate_config,check_trajectory
from .urscript_builder import compile_urscript


def literal(values,pose=False):
    return ('p' if pose else '')+'['+', '.join(f'{x:.9f}' for x in values)+']'


def waypoint(point,c):
    if point['mode']=='movej':return f"movej({literal(point['q'])}, a={c['acceleration']:.6f}, v={c['joint_rad_s']:.6f}, r=0)"
    return f"movel({literal(point['tcp'],True)}, a={c['acceleration']:.6f}, v={c['travel_mm_s']/1000:.6f}, r=0)"


def build_guarded_script(trajectory,c,job,options=None,dry_run=False,prepare_only=False):
    validate_config(c,verified=not dry_run)
    if not prepare_only:check_trajectory(c,trajectory)
    if type(job) is not int or not 0<job<2147483647:raise ValueError('任务编号无效。')
    options=dict(options or {});pin=c['output_pin']
    for key in ('include_prepare_pose','prepare_joint_degrees','program_name','output_pin'):options.pop(key,None)
    body=[]
    if not prepare_only:
        body=[waypoint(c['prepare'],c)]+[waypoint(p,c) for p in c['enter']]
        first=trajectory.points[0];last=trajectory.points[-1]
        def at(p,z):return literal([p.x_mm/1000,p.y_mm/1000,z/1000,*[math.radians(x) for x in (p.rx_deg,p.ry_deg,p.rz_deg)]],True)
        motion=lambda pose:f"movel({pose}, a={c['acceleration']:.6f}, v={c['travel_mm_s']/1000:.6f}, r=0)"
        g=c['workspace']
        anchor=literal([g['center_x_mm']/1000,g['center_y_mm']/1000,c['approach_z_mm']/1000,*[math.radians(x) for x in g['orientation_deg']]],True)
        body += [motion(anchor),motion(at(first,c['approach_z_mm'])),motion(at(first,first.z_mm))]
        import copy
        t=copy.deepcopy(trajectory)
        if dry_run:
            for p in t.points:p.drawing=False
        compiled=compile_urscript(t,output_pin=pin,include_prepare_pose=False,**options)
        body += [line.strip() for line in compiled.splitlines()[2:-2]]
        body += [f'set_standard_digital_out({pin}, False)',motion(at(last,c['approach_z_mm'])),motion(anchor)]
        body += [waypoint(p,c) for p in c['exit']]+[waypoint(c['prepare'],c)]
    else:body=[waypoint(c['prepare'],c)]
    # Start-position and TCP checks happen on the controller too, immediately
    # before any motion. A stale host-side sample cannot bypass these guards.
    q=literal(c['start']['q']);tcp=literal(c['tcp_offset'],True)
    prefix=[f'def guarded_job_{job}():',f'  set_standard_digital_out({pin}, False)',
            f'  set_runstate_standard_digital_output_to_value({pin}, 1)',
            '  write_output_integer_register(27, 0)',f'  write_output_integer_register(25, {job})',
            '  write_output_integer_register(26, 0)',
            '  local initial_heartbeat = read_input_integer_register(24)',
            '  local waiting_cycles = 0',
            '  while read_input_integer_register(24) == initial_heartbeat:',
            '    waiting_cycles = waiting_cycles+1',
            '    if waiting_cycles >= 250 or read_input_integer_register(26) != 0:',
            '      write_output_integer_register(26, -1)','      halt','    end','    sync()','  end',
            '  if read_input_integer_register(26) != 0 or norm(get_actual_joint_speeds()) > 0.002:',
            '    write_output_integer_register(26, -1)','    halt','  end',
            f'  local expected_q = {q}',
            f'  local expected_tcp = {tcp}', '  local current_q = get_actual_joint_positions()',
            '  local current_tcp = get_tcp_offset()', '  local i = 0', '  while i < 6:',
            f"    if abs(current_q[i]-expected_q[i]) > {math.radians(c['joint_tolerance_deg']):.9f}:",
            '      write_output_integer_register(26, -1)','      halt','    end',
            '    local tol = 0.0001','    if i >= 3:','      tol = 0.001','    end',
            '    if abs(current_tcp[i]-expected_tcp[i]) > tol:',
            '      write_output_integer_register(26, -1)','      halt','    end','    i = i+1','  end',
            f'  if read_input_integer_register(25) != {job}:',
            '    write_output_integer_register(26, -1)','    halt','  end',
            '  thread route_motion():','    write_output_integer_register(26, 1)']
    prefix += ['    '+line for line in body]
    prefix += [f'    set_standard_digital_out({pin}, False)',f'    write_output_integer_register(27, {job})',
               '    write_output_integer_register(26, 4)','  end',
               '  local heartbeat = read_input_integer_register(24)','  local stale_cycles = 0',
               '  local motion = run route_motion()',
               '  while read_output_integer_register(26) != 4:',
               '    local next_heartbeat = read_input_integer_register(24)',
               '    if next_heartbeat == heartbeat:','      stale_cycles = stale_cycles+1','    else:',
               '      heartbeat = next_heartbeat','      stale_cycles = 0','    end',
               f'    if stale_cycles >= 250 or read_input_integer_register(26) != 0 or read_input_integer_register(25) != {job}:',
               f'      set_standard_digital_out({pin}, False)','      kill motion','      stopj(1.0)',
               '      write_output_integer_register(26, -1)','      halt','    end','    sync()','  end',
               '  join motion','end',f'guarded_job_{job}()']
    return '\n'.join(prefix)+'\n'
