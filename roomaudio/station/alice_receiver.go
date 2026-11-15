// RoomAudio receives processed 16 kHz mono PCM from a private Unix datagram socket.
package main

import (
 "net"
 "os"
 "os/signal"
 "path/filepath"
 "syscall"
 "strconv"
 "time"
)

func main() {
 if len(os.Args) != 3 { os.Exit(2) }
 socketPath, leasePath := os.Args[1], os.Args[2]
 if filepath.Dir(socketPath) != filepath.Dir(leasePath) { os.Exit(2) }
 _ = os.Remove(socketPath)
 c, err := net.ListenUnixgram("unixgram", &net.UnixAddr{Name:socketPath, Net:"unixgram"}); if err != nil { os.Exit(3) }
 defer c.Close(); defer os.Remove(socketPath)
 if os.Chmod(socketPath,0600) != nil { os.Exit(4) }
 done:=make(chan os.Signal,1); signal.Notify(done,syscall.SIGTERM,syscall.SIGINT)
 go func(){ <-done; c.Close() }()
 buf:=make([]byte,4096); last:=time.Time{}
 for {
  _ = c.SetReadDeadline(time.Now().Add(30*time.Second))
  n,_,err:=c.ReadFromUnix(buf); if err!=nil { return }
  if n==0 || n%2!=0 { continue }
  if _,err=os.Stdout.Write(buf[:n]); err!=nil { return }
  if time.Since(last)>time.Second { tmp:=leasePath+".new"; if os.WriteFile(tmp,[]byte(strconv.FormatInt(time.Now().Unix(),10)),0600)!=nil{return}; if os.Rename(tmp,leasePath)!=nil{return}; last=time.Now() }
 }
}
