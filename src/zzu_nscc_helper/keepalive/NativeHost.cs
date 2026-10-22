using System; // 基础类型。
using System.IO; // 字节流与日志。
using System.IO.Pipes; // 仅本机命名管道。
using System.Text; // UTF8 编码。
using System.Threading; // 取消等待与线程可见性。
using System.Threading.Tasks; // 独立接收 Edge 消息。
class NativeHost { // 由 Edge 持有，助手退出后只等待，不产生网络流量。
    static volatile NamedPipeClientStream desktop = null; // 当前桌面通道。
    static readonly object outputLock = new object(); // 保护发给 Edge 的长度帧。
    static Stream edgeOutput; // Edge 提供的标准输出流。
    static CancellationTokenSource ending = new CancellationTokenSource(); // Edge 关闭时终止所有等待。
    static string pipeName="ZZDX-VPN-Tabs-v1"; // 正式桌面通道。
    static void Note(string stage) { // 诊断仅保存阶段，不保存消息内容。
        try { // 日志故障不影响连接。
            string folder=Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),"ZZU-NSCC-Helper","logs"); Directory.CreateDirectory(folder); // 本应用日志目录。
            string file=Path.Combine(folder,"native-status-"+DateTime.UtcNow.AddHours(8).ToString("yyyyMMdd")+".log"); // 北京日期按日存储。
            foreach(string old in Directory.GetFiles(folder,"native-status-????????.log")) { // 只处理自己的日期日志。
                DateTime date; if(DateTime.TryParseExact(Path.GetFileNameWithoutExtension(old).Substring(14),"yyyyMMdd",null,System.Globalization.DateTimeStyles.None,out date) && date.Date<DateTime.UtcNow.AddHours(8).Date.AddDays(-6)) File.Delete(old); // 保留最近七个日期。
            } // 完成日志清理。
            File.AppendAllText(file,DateTimeOffset.UtcNow.ToString("o")+" "+stage+Environment.NewLine); // 不写标题或网址。
        } catch {} // 日志不可用时继续连接。
    } // 结束诊断。
    static byte[] ReadExact(Stream input,int count) { // 处理分段到达的 Edge 帧。
        byte[] data=new byte[count]; int used=0; // 有上限的消息缓冲。
        while(used<count) { int n=input.Read(data,used,count-used); if(n==0) throw new EndOfStreamException(); used+=n; } // EOF 表示 Edge 已关闭连接。
        return data; // 返回完整字节。
    } // 结束读取。
    static void ToEdge(byte[] body) { // 多个来源也不能交错帧。
        lock(outputLock) { byte[] prefix=BitConverter.GetBytes(body.Length); edgeOutput.Write(prefix,0,4); edgeOutput.Write(body,0,body.Length); edgeOutput.Flush(); } // Native Messaging 二进制协议。
    } // 结束发送。
    static void Command(string command) { // 仅支持内部固定命令。
        ToEdge(Encoding.UTF8.GetBytes("{\"command\":\""+command+"\"}")); // 不拼接用户数据。
    } // 结束命令。
    static void ReceiveEdge(Stream input) { // 持续读取，助手关闭时也不让 Edge 管道堵塞。
        while(!ending.IsCancellationRequested) { // 仅在 Edge 仍持有连接时运行。
            int count=BitConverter.ToInt32(ReadExact(input,4),0); // 读取四字节长度。
            if(count<=0 || count>262144) throw new InvalidDataException(); // 限制内存。
            byte[] body=ReadExact(input,count); // 读取 JSON，但不记录正文。
            NamedPipeClientStream pipe=desktop; // 获取本次有效通道。
            if(pipe==null) continue; // 桌面不在时丢弃心跳与旧状态，不缓存绑定。
            try { pipe.Write(body,0,body.Length); pipe.WriteByte(10); pipe.Flush(); } // 转发至桌面。
            catch(IOException) {} catch(ObjectDisposedException) {} // 桌面重启时继续保持 Edge 连接。
        } // 等待下一帧。
    } // 结束接收。
    static void DesktopLoop() { // 低开销本机等待，替代浏览器三十秒唤醒轮询。
        while(!ending.IsCancellationRequested) { // Edge 退出时停止。
            var pipe=new NamedPipeClientStream(".",pipeName,PipeDirection.InOut,PipeOptions.Asynchronous); // 不开放 TCP。
            bool connected=false; // 未接入时不重复写断连日志。
            try { // 连接、读取与断连均可重建。
                pipe.Connect(500); // 桌面未启动时短时等待。
                desktop=pipe; connected=true; Note("DESKTOP_CONNECTED"); // 发布新通道。
                Command("stop"); Command("list"); // 每次重连撤销旧任务，再请求全新列表。
                var line=new MemoryStream(); // 桌面换行帧缓冲。
                while(!ending.IsCancellationRequested) { // 等待桌面发来命令。
                    int value=pipe.ReadByte(); if(value<0) throw new EndOfStreamException(); // 桌面退出立刻重建通道。
                    if(value==10) { ToEdge(line.ToArray()); line.SetLength(0); } // 完整命令转给 Edge。
                    else { line.WriteByte((byte)value); if(line.Length>262144) throw new InvalidDataException(); } // 限制单帧。
                } // 结束当前连接。
            } catch(TimeoutException) {} catch(IOException) {} catch(ObjectDisposedException) {} // 桌面退出是正常等待状态。
            finally { // 取消已失效通道与绑定权限。
                if(Object.ReferenceEquals(desktop,pipe)) desktop=null; // 不影响可能的新通道。
                pipe.Dispose(); // 关闭旧句柄。
                if(connected) { Note("DESKTOP_OFFLINE"); try { Command("stop"); } catch { ending.Cancel(); } } // 失联立即撤销扩展恢复权限。
            } // 清理完成。
            ending.Token.WaitHandle.WaitOne(250); // 无网络活动，最多约一秒发现桌面启动。
        } // 等待下一次桌面启动。
    } // 结束桌面监视。
    static int Main(string[] args) { // 所有模式都不启动浏览器或桌面助手。
        Note("EDGE_HOST_START"); // 只记录生命周期。
        try { // 验证固定扩展来源。
            string expected="chrome-extension://"+File.ReadAllText(Path.Combine(AppDomain.CurrentDomain.BaseDirectory,"extension-id.txt")).Trim()+"/"; // 固定来源。
            if(args.Length==0 || args[0]!=expected) return 2; // 拒绝其他扩展。
            string testPipe=Environment.GetEnvironmentVariable("ZZDX_VPN_TEST_PIPE"); if(testPipe!=null && testPipe.StartsWith("ZZDX-VPN-Test-")) pipeName=testPipe; // 测试子进程隔离，不改变系统环境。
            edgeOutput=Console.OpenStandardOutput(); // Edge 原生输出。
            var input=Console.OpenStandardInput(); // Edge 原生输入。
            var received=Task.Run(()=>ReceiveEdge(input)); // 始终消费 Edge 帧。
            var connector=Task.Run(()=>DesktopLoop()); // 本机断连后自动等待。
            int ended=Task.WaitAny(received,connector); // 任一方向异常终止整个宿主。
            if(ended==0) received.GetAwaiter().GetResult(); else connector.GetAwaiter().GetResult(); // 传播真实错误类别。
            return 0; // 正常结束。
        } catch(EndOfStreamException) { return 0; } // Edge 关闭连接是正常退出。
        catch(Exception error) { Note("EXIT_"+error.GetType().Name); return 1; } // 不保存异常原文。
        finally { ending.Cancel(); NamedPipeClientStream pipe=desktop; if(pipe!=null) pipe.Dispose(); Note("EDGE_HOST_EXIT"); } // Edge 退出后无残留等待进程。
    } // 结束入口。
} // 结束组件。
