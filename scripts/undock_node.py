#!/usr/bin/env python3
import rospy
from enum import Enum
from std_srvs.srv import Trigger, TriggerResponse
from geometry_msgs.msg import Twist
from sensor_msgs.msg import BatteryState
from actionlib_msgs.msg import GoalStatusArray, GoalStatus, GoalID

class UndockState(Enum):
    IDLE = 0
    DISCHARGE = 1
    MOVE_OUT_DOCK = 2
    SUCCESS = 3
    FAILED = 4
    CANCELLED = 5

class UndockExecutor:
    def __init__(self):
        self.is_undock_srv_triggered = False
        self.is_battery_stop_charge = False
        self.state = UndockState.IDLE
        battery_state_topic = rospy.get_param("~battery_state_topic","/xnergy_charger_rcu/battery_state")
        cmd_vel_topic = rospy.get_param("~cmd_vel_topic","/kopilot_user_cmd")
        self.trigger_stop_charge_srv = rospy.get_param("~trigger_stop_charge_srv","/xnergy_charger_rcu/trigger_stop")
        
        # Setup ros part
        self.xnergy_state_sub = rospy.Subscriber(battery_state_topic, BatteryState, self.check_discharge)
        self.cmd_kopilot_pub = rospy.Publisher(cmd_vel_topic, Twist, queue_size=10)
        self.undock_service = rospy.Service('~trigger', Trigger, self.handle_undock_request)
        self.undock_status_pub = rospy.Publisher('~status', GoalStatusArray, queue_size=10)
        self.undock_cancel_sub = rospy.Subscriber('~cancel', GoalID, self.handle_undock_cancel)

    def handle_undock_request(self, req):
        rospy.loginfo("Enable undocking")
        self.is_undock_srv_triggered = True
        return TriggerResponse(success=True)

    def set_undock_state(self, state):
        # This function to set the undock state
        # publish goalstatus for missys
        self.state = state
        msg = GoalStatusArray()
        msg.status_list = []
        goal_status = GoalStatus()
        
        if state == UndockState.IDLE:
            pass
        elif state == UndockState.SUCCESS:
            goal_status.status = GoalStatus.SUCCEEDED
            goal_status.text = "Undock successfully completed"
            rospy.loginfo(goal_status.text)
        elif state == UndockState.FAILED:
            goal_status.status = GoalStatus.ABORTED
            goal_status.text = "Undock Failed"
            rospy.logerr(goal_status.text)
        elif state == UndockState.CANCELLED:
            goal_status.status = GoalStatus.PREEMPTED
            goal_status.text = "Undock cancel"
            rospy.logwarn(goal_status.text)
        else:
            goal_status.status = GoalStatus.ACTIVE        

        msg.status_list.append(goal_status)
        self.undock_status_pub.publish(msg)

    def handle_undock_cancel(self, msg):
        rospy.logwarn("Undock srv cancel request received")
        self.set_undock_state(UndockState.CANCELLED)
    
    def check_discharge(self, msg: BatteryState):
        if msg.power_supply_status == BatteryState.POWER_SUPPLY_STATUS_NOT_CHARGING:
            self.is_battery_stop_charge = True
        else:
            self.is_battery_stop_charge = False

    def trigger_discharge(self):
        try:
            undock_trigger = rospy.ServiceProxy(self.trigger_stop_charge_srv, Trigger)
            res = undock_trigger()
            rospy.loginfo(f"Trigger stop charging srv, success: [{res.success}] | msg: {res.message}")
            if not res.success:
                return False
        except rospy.ServiceException as e:
            rospy.logerr(f"Stop charging call failed: {e}")
            return False

    def publish_cmd(self, linear_vel=0.0, angular_vel=0.0):
        # default trigger this function is asking the robot to stop
        msg = Twist()
        msg.linear.x = linear_vel
        msg.angular.z = angular_vel
        self.cmd_kopilot_pub.publish(msg)

class UndockStateMachine(UndockExecutor):
    def __init__(self):
        super(UndockStateMachine,self).__init__()
        rate = rospy.get_param("~rate", 1.0)         # default 1hz
        self.sleep_period = rospy.Rate(rate)
        self.init_param()
        
    def init_param(self):
        self.retry_count = 1
        self.is_undock_srv_triggered = False

    def start(self):
        while not rospy.is_shutdown():
            if self.is_undock_srv_triggered:
                if self.do_discharge() and self.do_moving():
                    # publish cmd_vel to 0 to stop
                    self.set_undock_state(UndockState.SUCCESS)
                    self.init_param()
                elif self.state == UndockState.CANCELLED:
                    # publish cmd_vel to 0 to stop robot from moving
                    self.publish_cmd()
                    self.init_param()
                else:
                    self.retry_count += 1
                    if self.retry_count > 3:
                        self.set_undock_state(UndockState.FAILED)
                        # init_param
                        self.init_param()
                        
            self.sleep_period.sleep()

    def do_discharge(self):
        # This function should monitor first trigger # Trigger /xnergy_charger_rcu/trigger_stop
        # wait until the the batteryState to uint8 POWER_SUPPLY_STATUS_NOT_CHARGING = 3
        # Or fail when Battery state is not in NOT_CHARGING state for more than 20 seconds.
        rospy.loginfo("Do Stop Charging")
        self.trigger_discharge()
        wait_for_sec = 20
        self.set_undock_state(UndockState.DISCHARGE)
        while ((not self.is_battery_stop_charge) and (wait_for_sec > 0)
            and self.state != UndockState.CANCELLED):
            rospy.loginfo("Waiting for charge to stop")
            rospy.sleep(1)
            wait_for_sec = wait_for_sec - 1
        if self.state == UndockState.CANCELLED:
            return False
        elif self.is_battery_stop_charge:
            rospy.loginfo("Successfully stop charging")
            return True
        else:
            rospy.logwarn("Charging is not stopped within 20 secs")
            return False
    
    def do_moving(self):
        # move to moving forward for 50cm through kopilot
        # ignoring cancellation for this state
        rospy.loginfo("Do Moving")
        self.set_undock_state(UndockState.MOVE_OUT_DOCK)
        for i in range(5):
            self.publish_cmd(linear_vel=0.1)
            rospy.sleep(1)
        # Stop the moving
        self.publish_cmd()
        return True


if __name__ == "__main__":
    rospy.init_node("undock_node", disable_signals=True)
    node = UndockStateMachine()
    node.start()
