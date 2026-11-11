package com.rideedge.app

import android.app.Activity
import android.os.Bundle
import android.graphics.*
import android.view.View
import android.widget.LinearLayout
import android.widget.TextView

/** Offline, Preview-only acceptance surface. Absent from the normal APK. */
class EdgeIconReviewActivity : Activity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val layout = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setBackgroundColor(Color.rgb(31,58,77))
            setPadding(24,(48*resources.displayMetrics.density).toInt(),24,24)
        }
        layout.addView(TextView(this).apply {
            text = "OFFLINE ICON REVIEW\nNormal / Preview / themed · 48dp\nCircle, squircle, rounded square"
            setTextColor(Color.WHITE); textSize = 18f
        })
        layout.addView(object : View(this) {
            val art = getDrawable(R.drawable.ic_rideedge_art)!!
            val preview = getDrawable(R.drawable.ic_launcher_foreground)!!
            val mono = getDrawable(R.drawable.ic_launcher_monochrome)!!
            override fun onDraw(canvas: Canvas) {
                super.onDraw(canvas)
                val d = resources.displayMetrics.density
                val paint = Paint(Paint.ANTI_ALIAS_FLAG)
                val size = 48*d
                for (row in 0..2) for (col in 0..2) {
                    val left = (18+col*112)*d; val top = (28+row*125)*d
                    canvas.save(); canvas.translate(left,top)
                    val mask = Path()
                    when (row) {
                        0 -> mask.addCircle(size/2,size/2,size/2,Path.Direction.CW)
                        1 -> { // Continuous rounded square (superellipse, exponent four).
                            for (step in 0..360) {
                                val a = Math.toRadians(step.toDouble())
                                val c = kotlin.math.cos(a); val s = kotlin.math.sin(a)
                                val x = (size/2*(1+kotlin.math.sign(c)*kotlin.math.sqrt(kotlin.math.abs(c)))).toFloat()
                                val y = (size/2*(1+kotlin.math.sign(s)*kotlin.math.sqrt(kotlin.math.abs(s)))).toFloat()
                                if (step == 0) mask.moveTo(x,y) else mask.lineTo(x,y)
                            }; mask.close()
                        }
                        else -> mask.addRoundRect(0f,0f,size,size,size*.22f,size*.22f,Path.Direction.CW)
                    }
                    canvas.clipPath(mask)
                    paint.color = if (col == 2) Color.rgb(185,198,208) else Color.rgb(31,58,77)
                    canvas.drawRect(0f,0f,size,size,paint)
                    val drawable = when(col) { 0 -> art; 1 -> preview; else -> mono }
                    drawable.setBounds((-size*.25f).toInt(),(-size*.25f).toInt(),(size*1.25f).toInt(),(size*1.25f).toInt())
                    if (col == 2) drawable.setTint(Color.rgb(31,58,77))
                    drawable.draw(canvas)
                    canvas.restore()
                    paint.color=Color.WHITE; paint.textSize=11*d
                    canvas.drawText(listOf("Normal","Preview","Themed")[col],left,top+size+20*d,paint)
                }
            }
        }, LinearLayout.LayoutParams(-1,-1))
        setContentView(layout)
    }
}
