import { test } from 'node:test';
import assert from 'node:assert/strict';
import { envForModel, type ModelsConfig } from '../src/config.js';
import { createDeepSeekSystemOne } from '../src/systemone/deepseek.js';

test('analysis is isolated from quick response configuration and cannot fall back', () => {
  const config: ModelsConfig = { defaultModel: 'jev', jev: {provider:'typesafe',apiKey:'jev'},
    deepseek:{provider:'openrouter',apiKey:'fast',model:'fast-model'},
    analyst:{provider:'ark',apiKey:'analysis',model:'analysis-model'} };
  const env=envForModel(config,'analyst',{});
  assert.equal(env.MODEL_API_KEY,'analysis');
  assert.equal(env.MODEL_NAME,'analysis-model');
  assert.match(env.MODEL_CHAT_URL!,/volces/);
  assert.equal(envForModel(config,'deepseek',{}).MODEL_NAME,'fast-model');
  const alternative=envForModel({...config,analyst:{provider:'openrouter',apiKey:'analysis-or',model:'deepseek/analysis'}},'analyst',{});
  assert.equal(alternative.MODEL_API_KEY,'analysis-or');
  assert.equal(alternative.MODEL_NAME,'deepseek/analysis');
  assert.match(alternative.MODEL_CHAT_URL!,/openrouter/);
  assert.deepEqual(JSON.parse(alternative.MODEL_EXTRA_BODY!),{reasoning:{effort:'none'},provider:{require_parameters:true,sort:'throughput'},max_tokens:3000});
  assert.equal(alternative.MODEL_ANALYSIS,'1');
  assert.throws(()=>envForModel({...config,analyst:undefined},'analyst',{}));
});

test('analysis JSON request omits short token cap and does not request logprobs', async () => {
  let body: any;
  const backend=createDeepSeekSystemOne({apiKey:'test',analysis:true,fetchImpl:async (_url,init)=>{
    body=JSON.parse(String(init?.body));
    return new Response(JSON.stringify({choices:[{finish_reason:'stop',message:{content:'{"phase":"explore"}'}}]}));
  }});
  const answer=await backend.ask({}, {plan:{type:'json',instructions:'Return JSON'}});
  assert.equal(answer.plan!.type,'json');
  assert.equal(body.max_tokens,undefined);
  assert.equal(body.logprobs,undefined);
});

