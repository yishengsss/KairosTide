"""Only explicit user turns may open fixed-event drafts."""

import re


def is_rigid_create_request(text: str) -> bool:
    utterance = text.strip()
    if not utterance or utterance.endswith(("?", "？")):
        return False
    if re.search(r"有什么|有哪些|查询|查看|取消|删除|请假|改成|修改|提前|推迟|最近", utterance):
        return False
    if re.search(r"找个时间|有空.*(?:学习|完成|写)|周日.*前完成", utterance):
        return False
    event = re.search(r"开.{0,20}会|上课|考试|预约|讲座|面试|会议|课程", utterance)
    temporal = re.search(r"明天|后天|今天|下周|本周|星期|周[一二三四五六日天]|\d{4}-\d{2}-\d{2}", utterance)
    explicit = re.search(r"创建|新建|加个|加一|安排|帮我添加|记个", utterance)
    return bool(event and (temporal or explicit))
