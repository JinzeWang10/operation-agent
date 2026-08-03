"""End-to-end: sample/text.txt -> FeatureBag -> LLM brief -> composite PNG.

Run from repo root:
    python -m app.incident.render_report
"""
from __future__ import annotations

import asyncio
import argparse
import json
import ast
import sys
import time
from pathlib import Path
from constant.const import common_area_dict, __latest_time_hours__, __weixin_chat_event_num__, __resource_event_system_type__
# from big_data_model.incident.charts import render_dashboard as render_dashboard_mpl
from big_data_model.incident.context import load_related_context, RelatedContext, IncidentTicket, ChangeTicket
from big_data_model.incident.features import extract
from big_data_model.incident.render.dashboard import render_dashboard as render_dashboard_html
from big_data_model.incident.summarizer import summarize
from service.service_prometheus import getNewNetisDimensionData, get_gaojing_centor, get_gaojing_ai_data
from service.service_duty import update_system, upgrade_system, latest_event
from database.db_duty import get_lx_id_by_order_number
from lanxin.service_api import delete_lx_user, update_lx_group_user, send_file_to_lx, send_image_to_lx
from constant.const import common_area_name_dict


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def get_order_info(system_name, influence_area):
    event_data = {}
    try:
        # 变更工单
        event_data["changes_header"] = "24小时内关联升级变更"
        event_data["changes"] = []
        update_content = update_system(system_name, influence_area)
        print("update_content：" + update_content)
        if update_content != "":
            update_str = update_content.split("\r\n")
            order_no = None
            order_time = ""
            order_title = ""
            for update_line in update_str:
                if len(update_line) < 2:
                    continue
                if update_line.startswith("CHM"):
                    if order_no is not None:
                        event_data["changes"].append({
                            "ticket_id": order_no,
                            "title": order_title,
                            "time_range": order_time,
                            "type_text": "常规变更"
                        })
                    order_no = update_line[:20]
                    order_title = update_line[20:]
                else:
                    order_time = update_line
            if order_no is not None:
                event_data["changes"].append({
                    "ticket_id": order_no,
                    "title": order_title,
                    "time_range": order_time,
                    "type_text": "常规变更"
                })
        # 升级工单
        upgrade_content = upgrade_system(system_name, influence_area)
        print("upgrade_content：" + upgrade_content)
        if upgrade_content != "":
            update_str = upgrade_content.split("\r\n")
            order_no = None
            order_time = ""
            order_title = ""
            for update_line in update_str:
                if len(update_line) < 2:
                    continue
                if update_line.startswith("DRM"):
                    if order_no is not None:
                        event_data["changes"].append({
                            "ticket_id": order_no,
                            "title": order_title,
                            "time_range": order_time,
                            "type_text": "版本升级"
                        })
                    order_no = update_line[:20]
                    order_title = update_line[21:]
                else:
                    order_time = update_line[5:]
            if order_no is not None:
                event_data["changes"].append({
                    "ticket_id": order_no,
                    "title": order_title,
                    "time_range": order_time,
                    "type_text": "版本升级"
                })
        event_content, count = latest_event([system_name], influence_area, {})
        if len(event_content) > 0:
            event_data["incidents"] = []
            if count > __weixin_chat_event_num__:
                event_content_title = str(__latest_time_hours__) + "小时内关联事件单(共" + str(count) + \
                                      "个)，以下是最近" + str(__weixin_chat_event_num__) + "条"
            else:
                event_content_title = str(__latest_time_hours__) + "小时内关联事件单(共" + str(count) + \
                                      "个)"
            event_data["incidents_header"] = event_content_title
            event_str = event_content[0].split("\r")

            for event_line in event_str:
                line_split = event_line.split("、")
                if len(line_split) > 1:
                    line_order_no = line_split[1][:20]
                    line_order_title = line_split[1][22:]
                    event_data["incidents"].append({
                        "ticket_id": line_order_no,
                        "severity": "重要",
                        "text": line_order_title
                    })
        # print(event_content)
        # print("event_content:" + event_content[0])
    except Exception as e:
        print(e)
    return event_data


async def main(condition) -> int:
    """
    {"order_number": order_number, "area_name": influence_area_name, "system_name": system_name,
                   "monitor_data": monitor_data, "app_id": app_id}
    """
    system_name = condition.get("system_name", "")
    influence_area_name = condition.get("area_name", "")
    influence_area = common_area_name_dict.get(influence_area_name, "ZB")
    monitor_start_time = "2026-05-20 10:00:00"
    end_time = "2026-05-20 10:10:00"
    order_number = condition.get("order_number", "")

    # monitor_data_list = get_gaojing_centor(system_name, influence_area_name, monitor_start_time, end_time, order_number)
    monitor_data = []
    monitor_data_list = condition.get("monitor_data", "")
    for monitor_line in monitor_data_list:
        # {'monitor': '核保规则发布情况', 'code': '2', 'type': '存在已发布核保规则', 'message': {'riskRule': '"AllUwRulePolicyApp_5100"已发布:1天:15小时'}}
        flag = True
        # if monitor_line["monitor"] == "核保规则发布情况":
        #     if "小时" in monitor_line["message"].get("riskRule", "") or "天" in monitor_line["message"].get("riskRule", ""):
        #         flag = False
        if  monitor_line["monitor"] in ["变更单信息", "升级单信息"]:
            flag = False
        if flag:
            monitor_data.append(monitor_line)
    # monitor_data = condition.get("monitor_data", "")
    engine = "html"
    payload_data = {'status': 0, 'statusText': 'Success', 'message': 'Success', 'timestamp': int(time.time()*1000), 'data': monitor_data}
    bag = extract(payload_data)
    brief = bag.to_llm_brief()
    event_data = get_order_info(system_name, influence_area)
    related_data = RelatedContext(
        incidents_header=event_data.get("incidents_header", ""),
        incidents=[IncidentTicket(**i) for i in event_data.get("incidents", [])],
        changes_header=event_data.get("changes_header", ""),
        changes=[ChangeTicket(**c) for c in event_data.get("changes", [])],
    )
    print("calling LLM for phenomenon brief...", flush=True)
    try:
        text = await summarize(brief)
    except Exception as e:  # noqa: BLE001 — LLM 任意失败都降级，不挡渲染和发图
        print(f"  LLM call failed ({type(e).__name__}: {e}); using fallback brief")
        text = "[LLM_ERROR]"
    # OUT_TXT.write_text(text, encoding="utf-8")
    # print(f"  brief saved -> {OUT_TXT.relative_to(HERE)}  ({len(text)} chars)")

    print("rendering composite PNG...", flush=True)
    OUT_PNG = "/home/web_app/monitor_png/" + str(order_number) + ".png"
    # render_dashboard(bag, OUT_PNG, brief_text=text, related=related_data, order_number=order_number)
    # print(f"rendering composite PNG (engine={engine})...", flush=True)
    if engine == "html":
        await render_dashboard_html(
            bag, OUT_PNG, brief_text=text, related=related_data, order_number=order_number
        )
    # else:
    #     render_dashboard_mpl(
    #         bag, OUT_PNG, brief_text=text, related=related_data, order_number=order_number
    #     )
    # print(f"  report saved -> {OUT_PNG.relative_to(HERE)}")
    # print(f"  report saved -> {OUT_PNG}")
    group_lx_ids = get_lx_id_by_order_number([order_number])
    if not group_lx_ids:
        print("未找到事件单【" + str(order_number) + "】对应的蓝信群，图已生成但跳过发送: " + OUT_PNG)
        return 0
    group_lx_id = group_lx_ids[0]
    print(group_lx_id)
    # group_lx_id = "12428032-JPh9HnaaX2bCJPkmgmtOvxa7uoqwl"
    send_image_to_lx(group_lx_id, OUT_PNG)
    return 0


def send_monitor_png_to_event_lx_group(condition):
    asyncio.run(main(condition))


if __name__ == '__main__':
    condition = {'order_number': 'INM-20260513-0046755', 'area_name': '四川', 'system_name':'第三代非车承保系统', 'monitor_data': [{'monitor': 'BPC监控', 'code': '1', 'type': '未返回异常信息', 'message': {'bpcAlarmtypeMap': {}}}, {'monitor': 'PROMETHEUS应用拨测结果', 'code': '1', 'type': '未返回异常信息', 'message': {'tcpNodes': '7', 'tcpAbnormalNodes': '0', 'tcpResponseParams': [], 'httpNodes': '0', 'httpAbnormalNodes': '0', 'httpResponseParams': []}}, {'monitor': '组件状态指标', 'code': '2', 'type': '返回组件信息状态', 'message': {'componentVOList': [{'comName': '总公司', 'sysName': '普惠金融保后管理平台', 'componentName': 'redis', 'clusterState': '', 'memoryState': ' ', 'roleState': ' ', 'instanceStateVOS': []}, {'comName': '总公司', 'sysName': '普惠金融保后管理平台', 'componentName': 'consul', 'clusterState': '', 'memoryState': '-', 'roleState': '-', 'instanceStateVOS': []}, {'comName': '总公司', 'sysName': '普惠金融保后管理平台', 'componentName': 'zuul', 'clusterState': '', 'memoryState': '-', 'roleState': '-', 'instanceStateVOS': []}]}}, {'monitor': '日志关键字指标', 'code': '2', 'type': '返回日志关键字指标', 'message': {'logManagementVOList': [{'sysName': '普惠金融保后管理平台', 'comName': '总公司', 'msg': '该系统没有配置日志关键字'}]}}, {'monitor': '调用链指标', 'code': '-1', 'type': '调用链指标接口查询失败 '}, {'monitor': '变更单信息', 'code': '-1', 'type': '变更情况接口查询失败  '}, {'monitor': '升级单信息', 'code': '-1', 'type': '升级情况接口查询失败  '}, {'monitor': '单客户端异常访问分析', 'code': '-1', 'type': '初步判断，非单客户端引起的异常。'}, {'monitor': '南中心告警', 'message': {'southCenterVOS': [{'urgent': ['【一般】/南中心机房/4-1机房/C14/海光机架服务器R5930 G2/219632010349(10.138.110.28)/NZX-南中心设备/x86服务器/中兴/R5930 G2_219632010349(10.138.110.28)/逻辑磁盘/1[状态 = 降级][带宽:256 KB,访问策略:读/写,损坏磁区表:空,后台初始化:启用后台初始化,后台任务:无,缓存策略:直接 IO,阵列卡:MegaRAID 9560-8i 4GB (263),物理磁盘:Raid 0 Slot 2, Raid 0 Slot 3, Raid 0 Slot 4, Raid 0 Slot 5, Raid 0 Slot 6, Raid 0 Slot 7, Raid 0 Slot 8, Raid 0 Slot 9, Raid 0 Slot 10, Raid 0 Slot 11,物理磁盘数量:10,前台任务:无,ID:1,读取策略:总提前读取,容量:32184 GB,SSD 快取:停用,状态:降级,类型:RAID 5,写入策略:回写]']}, {'virtual': []}]}}, {'monitor': '设备-主机', 'code': '1', 'type': '未返回异常信息', 'message': {'hostAlarmVO': [], 'hostinfo': [{'host': '10.2.5.236', 'cpuUsed': '0%', 'memory': '38%', 'iowait': '0', 'disk': '78%', 'running_days': '634'}, {'host': '10.2.36.89', 'cpuUsed': '8%', 'memory': '91%', 'iowait': '0.0013020833333328892', 'disk': '22%', 'running_days': '209'}, {'host': '10.2.5.252', 'cpuUsed': '0%', 'memory': '9%', 'iowait': '0.0002604166666723509', 'disk': '35%', 'running_days': '634'}, {'host': '10.2.11.171', 'cpuUsed': '0%', 'memory': '0%', 'iowait': '0', 'disk': '0%', 'running_days': '0'}, {'host': '10.2.28.37', 'cpuUsed': '0%', 'memory': '50%', 'iowait': '0.0000868055555555556', 'disk': '42%', 'running_days': '0'}, {'host': '10.2.5.250', 'cpuUsed': '0%', 'memory': '33%', 'iowait': '0', 'disk': '78%', 'running_days': '634'}, {'host': '10.2.5.238', 'cpuUsed': '0%', 'memory': '48%', 'iowait': '0.00026041666666642993', 'disk': '22%', 'running_days': '634'}, {'host': '10.28.89.216', 'cpuUsed': '1%', 'memory': '87%', 'iowait': '0.039062499999905256', 'disk': '42%', 'running_days': '210'}, {'host': '10.2.5.241', 'cpuUsed': '0%', 'memory': '28%', 'iowait': '0.00026041666666642993', 'disk': '22%', 'running_days': '634'}, {'host': '10.2.28.134', 'cpuUsed': '0%', 'memory': '89%', 'iowait': '0.005729166666661454', 'disk': '32%', 'running_days': '169'}, {'host': '10.2.5.246', 'cpuUsed': '0%', 'memory': '99%', 'iowait': '0', 'disk': '22%', 'running_days': '634'}, {'host': '10.2.69.80', 'cpuUsed': '13%', 'memory': '98%', 'iowait': '0.01770833333353039', 'disk': '65%', 'running_days': '713'}, {'host': '10.2.5.229', 'cpuUsed': '6%', 'memory': '17%', 'iowait': '0.0015625000000015397', 'disk': '30%', 'running_days': '634'}, {'host': '10.2.5.234', 'cpuUsed': '3%', 'memory': '23%', 'iowait': '0.0005208333333332297', 'disk': '23%', 'running_days': '634'}, {'host': '10.2.5.226', 'cpuUsed': '6%', 'memory': '20%', 'iowait': '0.0026041666666761403', 'disk': '29%', 'running_days': '634'}, {'host': '10.2.5.249', 'cpuUsed': '0%', 'memory': '79%', 'iowait': '0', 'disk': '22%', 'running_days': '634'}, {'host': '10.2.14.95', 'cpuUsed': '0%', 'memory': '39%', 'iowait': '0', 'disk': '13%', 'running_days': '536'}, {'host': '10.2.5.242', 'cpuUsed': '0%', 'memory': '48%', 'iowait': '0', 'disk': '22%', 'running_days': '634'}, {'host': '10.2.5.232', 'cpuUsed': '1%', 'memory': '70%', 'iowait': '0.004687500000043108', 'disk': '33%', 'running_days': '633'}, {'host': '10.2.28.39', 'cpuUsed': '0%', 'memory': '50%', 'iowait': '0', 'disk': '42%', 'running_days': '0'}, {'host': '10.5.12.138', 'cpuUsed': '0%', 'memory': '96%', 'iowait': '0', 'disk': '20%', 'running_days': '550'}, {'host': '10.2.65.216', 'cpuUsed': '0%', 'memory': '0%', 'iowait': '0', 'disk': '0%', 'running_days': '0'}, {'host': '10.2.70.170', 'cpuUsed': '0%', 'memory': '48%', 'iowait': '0', 'disk': '19%', 'running_days': '634'}, {'host': '10.2.5.221', 'cpuUsed': '6%', 'memory': '40%', 'iowait': '0.001041666666665719', 'disk': '31%', 'running_days': '634'}, {'host': '10.2.11.169', 'cpuUsed': '0%', 'memory': '0%', 'iowait': '0', 'disk': '0%', 'running_days': '0'}, {'host': '10.2.70.167', 'cpuUsed': '1%', 'memory': '17%', 'iowait': '0', 'disk': '37%', 'running_days': '634'}, {'host': '10.2.28.38', 'cpuUsed': '0%', 'memory': '50%', 'iowait': '0', 'disk': '42%', 'running_days': '0'}, {'host': '10.2.5.223', 'cpuUsed': '0%', 'memory': '47%', 'iowait': '0', 'disk': '32%', 'running_days': '633'}, {'host': '10.2.70.168', 'cpuUsed': '0%', 'memory': '16%', 'iowait': '0', 'disk': '38%', 'running_days': '634'}, {'host': '10.2.5.247', 'cpuUsed': '0%', 'memory': '64%', 'iowait': '0', 'disk': '22%', 'running_days': '634'}, {'host': '10.2.5.228', 'cpuUsed': '6%', 'memory': '18%', 'iowait': '0.0005208333333328596', 'disk': '30%', 'running_days': '634'}, {'host': '10.2.5.248', 'cpuUsed': '0%', 'memory': '72%', 'iowait': '0.00026041666666679986', 'disk': '22%', 'running_days': '634'}, {'host': '10.2.65.181', 'cpuUsed': '3%', 'memory': '62%', 'iowait': '0.02604166666666666', 'disk': '73%', 'running_days': '557'}, {'host': '10.2.36.91', 'cpuUsed': '3%', 'memory': '92%', 'iowait': '0.0069661458333333415', 'disk': '22%', 'running_days': '209'}, {'host': '10.2.5.235', 'cpuUsed': '3%', 'memory': '22%', 'iowait': '0.0002604166666664298', 'disk': '22%', 'running_days': '634'}, {'host': '10.2.65.217', 'cpuUsed': '0%', 'memory': '0%', 'iowait': '0', 'disk': '0%', 'running_days': '0'}, {'host': '10.2.5.253', 'cpuUsed': '0%', 'memory': '9%', 'iowait': '0', 'disk': '35%', 'running_days': '634'}, {'host': '10.2.5.245', 'cpuUsed': '0%', 'memory': '99%', 'iowait': '0.00026041666666642993', 'disk': '22%', 'running_days': '634'}, {'host': '10.2.70.171', 'cpuUsed': '0%', 'memory': '0%', 'iowait': '0', 'disk': '0%', 'running_days': '0'}, {'host': '10.2.14.91', 'cpuUsed': '0%', 'memory': '39%', 'iowait': '0.0020833333333788078', 'disk': '13%', 'running_days': '536'}, {'host': '10.2.28.137', 'cpuUsed': '1%', 'memory': '94%', 'iowait': '0.0007812500000022501', 'disk': '40%', 'running_days': '753'}, {'host': '10.2.14.94', 'cpuUsed': '0%', 'memory': '39%', 'iowait': '0.001041666666689404', 'disk': '13%', 'running_days': '536'}, {'host': '10.2.70.172', 'cpuUsed': '0%', 'memory': '0%', 'iowait': '0', 'disk': '0%', 'running_days': '0'}, {'host': '10.2.5.220', 'cpuUsed': '6%', 'memory': '22%', 'iowait': '0', 'disk': '33%', 'running_days': '634'}, {'host': '10.2.70.163', 'cpuUsed': '0%', 'memory': '4%', 'iowait': '0.0001302083333332149', 'disk': '14%', 'running_days': '634'}, {'host': '10.2.65.215', 'cpuUsed': '0%', 'memory': '0%', 'iowait': '0', 'disk': '0%', 'running_days': '0'}, {'host': '10.2.11.168', 'cpuUsed': '0%', 'memory': '0%', 'iowait': '0', 'disk': '0%', 'running_days': '0'}, {'host': '10.2.5.230', 'cpuUsed': '6%', 'memory': '17%', 'iowait': '0.001562473958765933', 'disk': '29%', 'running_days': '634'}, {'host': '10.2.5.240', 'cpuUsed': '2%', 'memory': '56%', 'iowait': '0.0002604166666671699', 'disk': '78%', 'running_days': '634'}, {'host': '10.2.65.214', 'cpuUsed': '0%', 'memory': '0%', 'iowait': '0', 'disk': '0%', 'running_days': '0'}, {'host': '10.2.14.90', 'cpuUsed': '1%', 'memory': '56%', 'iowait': '0.00104166666612097', 'disk': '48%', 'running_days': '536'}, {'host': '10.2.28.138', 'cpuUsed': '1%', 'memory': '94%', 'iowait': '0', 'disk': '31%', 'running_days': '753'}, {'host': '10.2.5.244', 'cpuUsed': '0%', 'memory': '99%', 'iowait': '0', 'disk': '22%', 'running_days': '634'}, {'host': '10.2.5.243', 'cpuUsed': '0%', 'memory': '32%', 'iowait': '0', 'disk': '22%', 'running_days': '634'}, {'host': '10.2.70.165', 'cpuUsed': '0%', 'memory': '14%', 'iowait': '0', 'disk': '13%', 'running_days': '634'}, {'host': '10.2.11.170', 'cpuUsed': '0%', 'memory': '0%', 'iowait': '0', 'disk': '0%', 'running_days': '0'}, {'host': '10.2.11.167', 'cpuUsed': '0%', 'memory': '0%', 'iowait': '0', 'disk': '0%', 'running_days': '0'}, {'host': '10.2.28.40', 'cpuUsed': '0%', 'memory': '50%', 'iowait': '0', 'disk': '37%', 'running_days': '0'}, {'host': '10.2.5.231', 'cpuUsed': '6%', 'memory': '17%', 'iowait': '0', 'disk': '29%', 'running_days': '634'}, {'host': '10.2.11.166', 'cpuUsed': '0%', 'memory': '0%', 'iowait': '0', 'disk': '0%', 'running_days': '0'}, {'host': '10.2.5.219', 'cpuUsed': '6%', 'memory': '22%', 'iowait': '0.0015624999999985791', 'disk': '33%', 'running_days': '634'}, {'host': '10.2.5.227', 'cpuUsed': '6%', 'memory': '21%', 'iowait': '0.0005208333333447022', 'disk': '29%', 'running_days': '634'}, {'host': '10.2.5.222', 'cpuUsed': '6%', 'memory': '98%', 'iowait': '0.0015625000000104217', 'disk': '30%', 'running_days': '634'}, {'host': '10.2.13.203', 'cpuUsed': '0%', 'memory': '21%', 'iowait': '0', 'disk': '13%', 'running_days': '265'}, {'host': '10.2.65.183', 'cpuUsed': '0%', 'memory': '94%', 'iowait': '0.0005208333333328595', 'disk': '21%', 'running_days': '769'}, {'host': '10.2.5.251', 'cpuUsed': '0%', 'memory': '8%', 'iowait': '0.00026041666666642993', 'disk': '22%', 'running_days': '634'}, {'host': '10.2.5.233', 'cpuUsed': '1%', 'memory': '72%', 'iowait': '0.0052083333333404385', 'disk': '55%', 'running_days': '633'}, {'host': '10.2.5.237', 'cpuUsed': '0%', 'memory': '8%', 'iowait': '0.0005208333333328599', 'disk': '22%', 'running_days': '634'}, {'host': '10.2.11.172', 'cpuUsed': '0%', 'memory': '0%', 'iowait': '0', 'disk': '0%', 'running_days': '0'}, {'host': '10.2.28.133', 'cpuUsed': '2%', 'memory': '89%', 'iowait': '0.002604166666628771', 'disk': '27%', 'running_days': '753'}, {'host': '10.2.70.169', 'cpuUsed': '0%', 'memory': '48%', 'iowait': '0', 'disk': '19%', 'running_days': '634'}, {'host': '10.2.11.173', 'cpuUsed': '0%', 'memory': '0%', 'iowait': '0', 'disk': '0%', 'running_days': '0'}, {'host': '10.2.65.180', 'cpuUsed': '11%', 'memory': '65%', 'iowait': '0.007291666666719247', 'disk': '82%', 'running_days': '769'}, {'host': '10.2.5.224', 'cpuUsed': '0%', 'memory': '23%', 'iowait': '0', 'disk': '39%', 'running_days': '633'}, {'host': '10.2.70.162', 'cpuUsed': '0%', 'memory': '6%', 'iowait': '0', 'disk': '13%', 'running_days': '634'}, {'host': '10.130.67.231', 'cpuUsed': '0%', 'memory': '0%', 'iowait': '0', 'disk': '0%', 'running_days': '0'}, {'host': '10.28.89.215', 'cpuUsed': '1%', 'memory': '93%', 'iowait': '0.03125000000001895', 'disk': '41%', 'running_days': '210'}, {'host': '10.2.5.239', 'cpuUsed': '0%', 'memory': '53%', 'iowait': '0', 'disk': '22%', 'running_days': '634'}, {'host': '10.2.5.218', 'cpuUsed': '0%', 'memory': '0%', 'iowait': '0', 'disk': '0%', 'running_days': '0'}, {'host': '10.2.36.90', 'cpuUsed': '3%', 'memory': '89%', 'iowait': '0.008501870934798343', 'disk': '22%', 'running_days': '209'}, {'host': '10.2.65.182', 'cpuUsed': '0%', 'memory': '39%', 'iowait': '0', 'disk': '24%', 'running_days': '769'}, {'host': '10.2.70.166', 'cpuUsed': '0%', 'memory': '13%', 'iowait': '0', 'disk': '13%', 'running_days': '634'}]}}, {'monitor': '设备-数据库', 'code': '1', 'type': '未返回异常信息', 'message': {'hostAlarmVO': [], 'dbinfo': [{'host': '10.2.28.134', 'dbType': 'ora', 'dbStatus': '1', 'cpuUsed': '0%', 'activeConn': '1', 'ybp': '0', 'memory': '89%', 'iowait': '0.005729166666661454', 'disk': '32%', 'running_days': '169'}, {'host': '10.2.36.90', 'dbType': 'gaussdb', 'dbStatus': '1', 'cpuUsed': '3%', 'activeConn': '9', 'ybp': '', 'memory': '89%', 'iowait': '0.008501870934798343', 'disk': '22%', 'running_days': '209'}, {'host': '10.2.28.137', 'dbType': 'ora', 'dbStatus': '1', 'cpuUsed': '1%', 'activeConn': '1', 'ybp': '0', 'memory': '94%', 'iowait': '0.0007812500000022501', 'disk': '40%', 'running_days': '719'}, {'host': '10.2.28.133', 'dbType': 'ora', 'dbStatus': '1', 'cpuUsed': '2%', 'activeConn': '1', 'ybp': '0', 'memory': '89%', 'iowait': '0.002604166666628771', 'disk': '27%', 'running_days': '719'}, {'host': '10.2.28.138', 'dbType': 'ora', 'dbStatus': '1', 'cpuUsed': '1%', 'activeConn': '1', 'ybp': '0', 'memory': '94%', 'iowait': '0', 'disk': '31%', 'running_days': '634'}, {'host': '10.2.28.37', 'dbType': 'ora', 'dbStatus': '0', 'cpuUsed': '0%', 'activeConn': '0', 'ybp': '0', 'memory': '50%', 'iowait': '0.0000868055555555556', 'disk': '42%', 'running_days': '0'}, {'host': '10.2.36.91', 'dbType': 'gaussdb', 'dbStatus': '1', 'cpuUsed': '3%', 'activeConn': '9', 'ybp': '', 'memory': '92%', 'iowait': '0.0069661458333333415', 'disk': '22%', 'running_days': '209'}, {'host': '10.2.28.40', 'dbType': 'ora', 'dbStatus': '0', 'cpuUsed': '0%', 'activeConn': '0', 'ybp': '0', 'memory': '50%', 'iowait': '0', 'disk': '37%', 'running_days': '0'}, {'host': '10.2.28.38', 'dbType': 'ora', 'dbStatus': '0', 'cpuUsed': '0%', 'activeConn': '0', 'ybp': '0', 'memory': '50%', 'iowait': '0', 'disk': '42%', 'running_days': '0'}, {'host': '10.2.36.89', 'dbType': 'gaussdb', 'dbStatus': '1', 'cpuUsed': '8%', 'activeConn': '28', 'ybp': '', 'memory': '91%', 'iowait': '0.0013020833333328892', 'disk': '22%', 'running_days': '209'}, {'host': '10.2.28.39', 'dbType': 'ora', 'dbStatus': '0', 'cpuUsed': '0%', 'activeConn': '0', 'ybp': '0', 'memory': '50%', 'iowait': '0', 'disk': '42%', 'running_days': '0'}]}}], 'app_id': '019L'}
    send_monitor_png_to_event_lx_group(condition)
