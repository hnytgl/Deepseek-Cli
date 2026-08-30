package com.sproutspeak.kids;

import android.Manifest;
import android.annotation.SuppressLint;
import android.app.Activity;
import android.content.SharedPreferences;
import android.content.pm.PackageManager;
import android.os.Bundle;
import android.speech.RecognitionListener;
import android.speech.RecognizerIntent;
import android.speech.SpeechRecognizer;
import android.speech.tts.TextToSpeech;
import android.speech.tts.UtteranceProgressListener;
import android.webkit.JavascriptInterface;
import android.webkit.WebView;
import android.webkit.WebViewClient;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.BufferedReader;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.Locale;

public class MainActivity extends Activity {
    private static final int REQ_MIC = 1002;
    private static final String MODEL = "deepseek-v4-flash";
    private static final String PREFS = "sproutspeak_local";
    private static final String KEY_NAME = "deepseek_api_key";

    private WebView webView;
    private TextToSpeech tts;
    private SpeechRecognizer speechRecognizer;
    private SharedPreferences prefs;
    private String speechTarget = "chat";
    private String lastPartialText = "";
    private boolean pendingSpeech = false;
    private boolean speechActive = false;
    private boolean ttsReady = false;

    @SuppressLint({"SetJavaScriptEnabled", "AddJavascriptInterface"})
    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        prefs = getSharedPreferences(PREFS, MODE_PRIVATE);
        webView = new WebView(this);
        setContentView(webView);
        webView.getSettings().setJavaScriptEnabled(true);
        webView.getSettings().setDomStorageEnabled(true);
        webView.getSettings().setAllowFileAccess(true);
        webView.getSettings().setMediaPlaybackRequiresUserGesture(false);
        webView.setWebViewClient(new WebViewClient());
        webView.addJavascriptInterface(new AppBridge(), "AndroidBridge");
        initTts();
        initSpeechRecognizer();
        webView.loadUrl("file:///android_asset/index.html");
    }

    private void initTts() {
        tts = new TextToSpeech(this, status -> {
            if (status == TextToSpeech.SUCCESS) {
                ttsReady = true;
                tts.setLanguage(Locale.US);
                tts.setSpeechRate(0.84f);
                tts.setPitch(1.03f);
                tts.setOnUtteranceProgressListener(new UtteranceProgressListener() {
                    @Override public void onStart(String utteranceId) {
                        js("window.onNativeTtsStart && window.onNativeTtsStart();");
                    }
                    @Override public void onDone(String utteranceId) {
                        js("window.onNativeTtsDone && window.onNativeTtsDone();");
                    }
                    @Override public void onError(String utteranceId) {
                        js("window.onNativeTtsDone && window.onNativeTtsDone();");
                    }
                });
            } else {
                ttsReady = false;
                js("window.onNativeTtsError && window.onNativeTtsError('系统英语朗读初始化失败');");
            }
        });
    }

    private void initSpeechRecognizer() {
        try {
            if (!SpeechRecognizer.isRecognitionAvailable(this)) {
                speechRecognizer = null;
                return;
            }
            speechRecognizer = SpeechRecognizer.createSpeechRecognizer(this);
            speechRecognizer.setRecognitionListener(new RecognitionListener() {
                @Override public void onReadyForSpeech(Bundle params) {
                    speechActive = true;
                    lastPartialText = "";
                    js("window.onNativeSpeechState && window.onNativeSpeechState('ready');");
                }
                @Override public void onBeginningOfSpeech() {
                    js("window.onNativeSpeechState && window.onNativeSpeechState('speaking');");
                }
                @Override public void onRmsChanged(float rmsdB) {
                    js("window.onNativeVoiceLevel && window.onNativeVoiceLevel(" + rmsdB + ");");
                }
                @Override public void onBufferReceived(byte[] buffer) {}
                @Override public void onEndOfSpeech() {
                    js("window.onNativeSpeechState && window.onNativeSpeechState('processing');");
                }
                @Override public void onError(int error) {
                    speechActive = false;
                    if (!lastPartialText.trim().isEmpty() &&
                            (error == SpeechRecognizer.ERROR_NO_MATCH || error == SpeechRecognizer.ERROR_SPEECH_TIMEOUT || error == SpeechRecognizer.ERROR_CLIENT)) {
                        deliverSpeech(lastPartialText, -1);
                        lastPartialText = "";
                        return;
                    }
                    String msg = speechError(error);
                    lastPartialText = "";
                    js("window.onNativeSpeechError && window.onNativeSpeechError(" + JSONObject.quote(msg) + ");");
                }
                @Override public void onResults(Bundle results) {
                    speechActive = false;
                    ArrayList<String> list = results.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION);
                    float[] conf = results.getFloatArray(SpeechRecognizer.CONFIDENCE_SCORES);
                    String text = list != null && !list.isEmpty() ? list.get(0) : lastPartialText;
                    double confidence = conf != null && conf.length > 0 ? conf[0] : -1;
                    deliverSpeech(text == null ? "" : text, confidence);
                    lastPartialText = "";
                }
                @Override public void onPartialResults(Bundle partialResults) {
                    ArrayList<String> list = partialResults.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION);
                    String text = list != null && !list.isEmpty() ? list.get(0) : "";
                    if (!text.trim().isEmpty()) lastPartialText = text;
                    js("window.onNativeSpeechPartial && window.onNativeSpeechPartial(" + JSONObject.quote(speechTarget) + "," + JSONObject.quote(text) + ");");
                }
                @Override public void onEvent(int eventType, Bundle params) {}
            });
        } catch (Exception e) {
            speechRecognizer = null;
        }
    }

    private void deliverSpeech(String text, double confidence) {
        String clean = text == null ? "" : text.trim();
        if (clean.isEmpty()) {
            js("window.onNativeSpeechError && window.onNativeSpeechError('没有识别到有效语音，请再说一次');");
            return;
        }
        js("window.onNativeSpeech && window.onNativeSpeech(" + JSONObject.quote(speechTarget) + "," + JSONObject.quote(clean) + "," + confidence + ");");
    }

    public class AppBridge {
        @JavascriptInterface public void startSpeech(String target) {
            runOnUiThread(() -> {
                speechTarget = target == null ? "chat" : target;
                if (android.os.Build.VERSION.SDK_INT >= 23 && checkSelfPermission(Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) {
                    pendingSpeech = true;
                    requestPermissions(new String[]{Manifest.permission.RECORD_AUDIO}, REQ_MIC);
                } else {
                    startListeningInternal();
                }
            });
        }

        @JavascriptInterface public void stopSpeech() {
            runOnUiThread(() -> {
                if (speechRecognizer != null && speechActive) {
                    try { speechRecognizer.stopListening(); } catch (Exception ignored) {}
                }
            });
        }

        @JavascriptInterface public void speak(String text) {
            runOnUiThread(() -> {
                if (tts != null && ttsReady && text != null && !text.trim().isEmpty()) {
                    if (speechRecognizer != null && speechActive) {
                        try { speechRecognizer.cancel(); } catch (Exception ignored) {}
                        speechActive = false;
                    }
                    tts.speak(text, TextToSpeech.QUEUE_FLUSH, null, "sproutspeak_turn");
                } else {
                    js("window.onNativeTtsDone && window.onNativeTtsDone();");
                }
            });
        }

        @JavascriptInterface public String saveApiKey(String key) {
            if (key == null) return "API Key 为空";
            String clean = key.replaceAll("\\s+", "").trim();
            if (clean.length() < 20) return "API Key 看起来不完整，请重新复制粘贴";
            prefs.edit().putString(KEY_NAME, clean).apply();
            return "OK";
        }

        @JavascriptInterface public boolean hasApiKey() {
            return !prefs.getString(KEY_NAME, "").trim().isEmpty();
        }

        @JavascriptInterface public void clearApiKey() {
            prefs.edit().remove(KEY_NAME).apply();
        }

        @JavascriptInterface public String modelName() { return MODEL; }
        @JavascriptInterface public boolean speechAvailable() { return speechRecognizer != null; }
        @JavascriptInterface public boolean ttsAvailable() { return ttsReady; }
        @JavascriptInterface public String deviceInfo() { return "Android " + android.os.Build.VERSION.RELEASE + " / SDK " + android.os.Build.VERSION.SDK_INT; }

        @JavascriptInterface public void chat(String messagesJson, String requestId) {
            new Thread(() -> doDeepSeek(messagesJson, requestId)).start();
        }
    }

    private void startListeningInternal() {
        if (speechRecognizer == null) {
            initSpeechRecognizer();
        }
        if (speechRecognizer == null) {
            js("window.onNativeSpeechError && window.onNativeSpeechError('当前平板没有可用的系统语音识别服务，请检查 Google 语音服务或系统语音输入');");
            return;
        }
        try {
            if (tts != null) tts.stop();
            try { speechRecognizer.cancel(); } catch (Exception ignored) {}
            lastPartialText = "";
            android.content.Intent intent = new android.content.Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH);
            intent.putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM);
            intent.putExtra(RecognizerIntent.EXTRA_LANGUAGE, "en-US");
            intent.putExtra(RecognizerIntent.EXTRA_LANGUAGE_PREFERENCE, "en-US");
            intent.putExtra(RecognizerIntent.EXTRA_PARTIAL_RESULTS, true);
            intent.putExtra(RecognizerIntent.EXTRA_MAX_RESULTS, 3);
            intent.putExtra(RecognizerIntent.EXTRA_PREFER_OFFLINE, false);
            intent.putExtra(RecognizerIntent.EXTRA_SPEECH_INPUT_MINIMUM_LENGTH_MILLIS, 500L);
            intent.putExtra(RecognizerIntent.EXTRA_SPEECH_INPUT_COMPLETE_SILENCE_LENGTH_MILLIS, 1200L);
            intent.putExtra(RecognizerIntent.EXTRA_SPEECH_INPUT_POSSIBLY_COMPLETE_SILENCE_LENGTH_MILLIS, 800L);
            speechRecognizer.startListening(intent);
        } catch (Exception e) {
            speechActive = false;
            js("window.onNativeSpeechError && window.onNativeSpeechError(" + JSONObject.quote("启动语音识别失败：" + e.getMessage()) + ");");
        }
    }

    private String speechError(int error) {
        switch (error) {
            case SpeechRecognizer.ERROR_AUDIO: return "录音出现问题，请检查麦克风";
            case SpeechRecognizer.ERROR_CLIENT: return "语音识别已停止，请重试";
            case SpeechRecognizer.ERROR_INSUFFICIENT_PERMISSIONS: return "没有麦克风权限，请在系统设置中允许";
            case SpeechRecognizer.ERROR_NETWORK:
            case SpeechRecognizer.ERROR_NETWORK_TIMEOUT: return "系统语音识别网络异常，请检查网络后重试";
            case SpeechRecognizer.ERROR_NO_MATCH: return "没有听清，请再说一次";
            case SpeechRecognizer.ERROR_RECOGNIZER_BUSY: return "语音识别正忙，请稍后再试";
            case SpeechRecognizer.ERROR_SERVER: return "系统语音识别服务暂时不可用";
            case SpeechRecognizer.ERROR_SPEECH_TIMEOUT: return "没有检测到说话声音";
            default: return "语音识别失败（错误码 " + error + "）";
        }
    }

    @Override public void onRequestPermissionsResult(int requestCode, String[] permissions, int[] grantResults) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults);
        if (requestCode == REQ_MIC) {
            if (grantResults.length > 0 && grantResults[0] == PackageManager.PERMISSION_GRANTED && pendingSpeech) {
                startListeningInternal();
            } else {
                js("window.onNativeSpeechError && window.onNativeSpeechError('需要麦克风权限才能进行口语练习');");
            }
            pendingSpeech = false;
        }
    }

    private void doDeepSeek(String messagesJson, String requestId) {
        HttpURLConnection conn = null;
        try {
            String apiKey = prefs.getString(KEY_NAME, "").trim();
            if (apiKey.isEmpty()) throw new Exception("请先在设置中保存 DeepSeek API Key");

            JSONObject body = new JSONObject();
            body.put("model", MODEL);
            body.put("messages", new JSONArray(messagesJson));
            body.put("stream", false);
            body.put("temperature", 0.7);

            URL u = new URL("https://api.deepseek.com/chat/completions");
            conn = (HttpURLConnection) u.openConnection();
            conn.setConnectTimeout(20000);
            conn.setReadTimeout(60000);
            conn.setRequestMethod("POST");
            conn.setDoOutput(true);
            conn.setRequestProperty("Content-Type", "application/json; charset=utf-8");
            conn.setRequestProperty("Accept", "application/json");
            conn.setRequestProperty("Authorization", "Bearer " + apiKey);
            try (OutputStream os = conn.getOutputStream()) {
                os.write(body.toString().getBytes(StandardCharsets.UTF_8));
            }

            int code = conn.getResponseCode();
            InputStream in = code >= 200 && code < 300 ? conn.getInputStream() : conn.getErrorStream();
            String raw = readAll(in);
            if (code < 200 || code >= 300) {
                String msg = raw;
                try {
                    JSONObject err = new JSONObject(raw).optJSONObject("error");
                    if (err != null) msg = err.optString("message", raw);
                } catch (Exception ignored) {}
                throw new Exception("DeepSeek API " + code + ": " + msg);
            }
            JSONObject data = new JSONObject(raw);
            String content = data.getJSONArray("choices").getJSONObject(0).getJSONObject("message").optString("content", "");
            callbackChat(requestId, true, content);
        } catch (Exception e) {
            callbackChat(requestId, false, e.getMessage() == null ? "请求失败" : e.getMessage());
        } finally {
            if (conn != null) conn.disconnect();
        }
    }

    private String readAll(InputStream in) throws Exception {
        if (in == null) return "";
        BufferedReader br = new BufferedReader(new InputStreamReader(in, StandardCharsets.UTF_8));
        StringBuilder sb = new StringBuilder();
        String line;
        while ((line = br.readLine()) != null) sb.append(line).append('\n');
        return sb.toString();
    }

    private void callbackChat(String id, boolean ok, String value) {
        js("window.onAndroidChat && window.onAndroidChat(" + JSONObject.quote(id == null ? "" : id) + "," + ok + "," + JSONObject.quote(value == null ? "" : value) + ");");
    }

    private void js(String script) {
        runOnUiThread(() -> {
            if (webView != null) webView.evaluateJavascript(script, null);
        });
    }

    @Override public void onBackPressed() {
        if (webView != null && webView.canGoBack()) webView.goBack();
        else super.onBackPressed();
    }

    @Override protected void onDestroy() {
        if (speechRecognizer != null) {
            try { speechRecognizer.cancel(); } catch (Exception ignored) {}
            speechRecognizer.destroy();
        }
        if (tts != null) { tts.stop(); tts.shutdown(); }
        if (webView != null) webView.destroy();
        super.onDestroy();
    }
}
