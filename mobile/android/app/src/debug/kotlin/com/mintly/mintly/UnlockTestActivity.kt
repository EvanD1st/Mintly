package com.mintly.mintly

import android.app.Activity
import android.os.Bundle
import android.widget.TextView
import java.util.concurrent.CountDownLatch

/** Emulator instrumentation host. This class is excluded from signed release APKs. */
class UnlockTestActivity : Activity() {
    val unlock by lazy { DeviceUnlock(this) }
    var completed = CountDownLatch(1)
    @Volatile var accepted = false
    override fun onCreate(state: Bundle?) { super.onCreate(state);setContentView(TextView(this).apply { text="Disposable Mintly unlock test" }) }
    fun authenticate() {
        completed=CountDownLatch(1);accepted=false
        unlock.request { accepted=it;completed.countDown() }
    }
    override fun onActivityResult(request: Int, result: Int, data: android.content.Intent?) {
        if (!unlock.activityResult(request,result)) super.onActivityResult(request,result,data)
    }
    override fun onDestroy() { unlock.close();super.onDestroy() }
}
