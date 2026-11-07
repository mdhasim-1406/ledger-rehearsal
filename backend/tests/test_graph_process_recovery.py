"""Actual production graph subprocess recovery and cross-process serialization."""
import json
import os
from pathlib import Path
import subprocess
import sys

SCRIPT=r'''
import os,json,time
from pathlib import Path
import httpx
from backend.investigation_agent import InvestigationAgent
folder=Path(os.environ['CASE_DIR'])
def response(request):
    body=json.loads(request.content)
    with (folder/'calls').open('a') as f:f.write('model\n');f.flush();os.fsync(f.fileno())
    if not any(m['role']=='tool' for m in body['messages']):
        time.sleep(.2)
        return httpx.Response(200,json={'choices':[{'message':{'tool_calls':[{'id':'one','type':'function','function':{'name':'get_evidence','arguments':'{"ids":["s"]}'}}]}}]})
    if os.environ.get('CRASH')=='1':os._exit(77)
    return httpx.Response(200,json={'choices':[{'message':{'content':json.dumps({'case_id':'c','status':'proposed','hypotheses':[{'statement':'observed','evidence_ids':['s'],'confidence':.5}]})}}]})
agent=InvestigationAgent(transport=httpx.MockTransport(response),checkpoint_db=folder/'graph.sqlite')
if os.environ.get('CRASH')=='1':
    original=agent._build
    def build():
        builder=original()
        # Crash before final model request, AFTER committed tools checkpoint.
        old=builder.nodes['model'].runnable
        def node(state):
            if any(m['role']=='tool' for m in state['messages']):os._exit(77)
            return old.invoke(state)
        from langgraph.utils.runnable import RunnableCallable
        builder.nodes['model'].runnable=RunnableCallable(node)
        return builder
    agent._build=build
result=agent.investigate('c',[{'id':'s','value':'synthetic'}])
assert result.status=='proposed',result
'''


def env_for(folder):
    env=os.environ.copy()
    env.update(CASE_DIR=str(folder),INVESTIGATION_LLM_BASE_URL='https://mock.invalid/v1',INVESTIGATION_LLM_MODEL='synthetic',INVESTIGATION_LLM_API_KEY='synthetic-only')
    return env


def test_actual_graph_process_resume_does_not_repeat_completed_model_or_tool(tmp_path):
    env=env_for(tmp_path);env['CRASH']='1'
    first=subprocess.run([sys.executable,'-c',SCRIPT],env=env,capture_output=True,text=True,timeout=20)
    assert first.returncode==77,first.stderr
    env.pop('CRASH')
    second=subprocess.run([sys.executable,'-c',SCRIPT],env=env,capture_output=True,text=True,timeout=20)
    assert second.returncode==0,second.stderr
    assert (tmp_path/'calls').read_text().splitlines()==['model','model']


def test_actual_graph_cross_process_same_identity_is_serialized(tmp_path):
    env=env_for(tmp_path)
    processes=[subprocess.Popen([sys.executable,'-c',SCRIPT],env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True) for _ in range(2)]
    for process in processes:
        stdout,stderr=process.communicate(timeout=20)
        assert process.returncode==0,stderr
    assert (tmp_path/'calls').read_text().splitlines()==['model','model']
