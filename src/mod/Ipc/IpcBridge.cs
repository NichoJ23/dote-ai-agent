using System;
using System.Net;
using System.Net.Sockets;
using System.Text;
using BepInEx.Logging;

namespace DotEAgent.Ipc
{
    /// <summary>
    /// TCP-based IPC bridge using length-prefixed framing.
    /// Frame format: [4-byte big-endian payload length][UTF-8 JSON payload]
    /// 
    /// Port 5555: State channel (mod pushes state to Python)
    /// Port 5556: Action channel (Python sends commands, mod replies with results)
    /// 
    /// Both listeners accept a single client at a time. If the client disconnects,
    /// the listener re-accepts on the next operation attempt.
    /// </summary>
    public class IpcBridge : IIpcBridge
    {
        private const int StatePort = 5555;
        private const int ActionPort = 5556;
        private const int ReadBufferSize = 65536;

        private static ManualLogSource Log { get { return Plugin.Log; } }

        private TcpListener stateListener;
        private TcpListener actionListener;
        private TcpClient stateClient;
        private TcpClient actionClient;
        private NetworkStream stateStream;
        private NetworkStream actionStream;

        private byte[] readBuffer = new byte[ReadBufferSize];
        private bool disposed;

        public bool IsStateConnected
        {
            get { return stateClient != null && stateClient.Connected; }
        }

        public bool IsActionConnected
        {
            get { return actionClient != null && actionClient.Connected; }
        }

        public void Start()
        {
            stateListener = new TcpListener(IPAddress.Loopback, StatePort);
            stateListener.Start();
            Log.LogInfo("IPC: State listener started on port " + StatePort);

            actionListener = new TcpListener(IPAddress.Loopback, ActionPort);
            actionListener.Start();
            Log.LogInfo("IPC: Action listener started on port " + ActionPort);
        }

        /// <summary>
        /// Attempts to accept any pending client connections on both ports.
        /// Call this every frame so connections are picked up promptly.
        /// </summary>
        public void AcceptClients()
        {
            TryAcceptStateClient();
            TryAcceptActionClient();
        }

        public void SendState(string jsonPayload)
        {
            if (!TryAcceptStateClient())
                return;

            if (!TrySend(stateStream, jsonPayload))
            {
                DisconnectState();
            }
        }

        public string PollAction()
        {
            if (!TryAcceptActionClient())
                return null;

            return TryReceive(actionStream);
        }

        public void SendResponse(string jsonPayload)
        {
            if (!IsActionConnected || actionStream == null)
                return;

            if (!TrySend(actionStream, jsonPayload))
            {
                DisconnectAction();
            }
        }

        public void Dispose()
        {
            if (disposed)
                return;
            disposed = true;

            DisconnectState();
            DisconnectAction();

            if (stateListener != null)
            {
                try { stateListener.Stop(); } catch (Exception) { }
                stateListener = null;
            }
            if (actionListener != null)
            {
                try { actionListener.Stop(); } catch (Exception) { }
                actionListener = null;
            }

            Log.LogInfo("IPC: Bridge disposed");
        }

        // --- Private helpers ---

        /// <summary>
        /// Accepts a pending state client if none is connected.
        /// Returns true if a client is connected and ready.
        /// </summary>
        private bool TryAcceptStateClient()
        {
            if (IsStateConnected)
                return true;

            // Clean up previous dead connection
            if (stateClient != null)
            {
                DisconnectState();
            }

            if (stateListener == null || !stateListener.Pending())
                return false;

            try
            {
                stateClient = stateListener.AcceptTcpClient();
                stateClient.NoDelay = true;
                stateStream = stateClient.GetStream();
                Log.LogInfo("IPC: State client connected from " + stateClient.Client.RemoteEndPoint);
                return true;
            }
            catch (Exception ex)
            {
                Log.LogWarning("IPC: Failed to accept state client: " + ex.Message);
                return false;
            }
        }

        /// <summary>
        /// Accepts a pending action client if none is connected.
        /// Returns true if a client is connected and ready.
        /// </summary>
        private bool TryAcceptActionClient()
        {
            if (IsActionConnected)
                return true;

            if (actionClient != null)
            {
                DisconnectAction();
            }

            if (actionListener == null || !actionListener.Pending())
                return false;

            try
            {
                actionClient = actionListener.AcceptTcpClient();
                actionClient.NoDelay = true;
                actionStream = actionClient.GetStream();
                Log.LogInfo("IPC: Action client connected from " + actionClient.Client.RemoteEndPoint);
                return true;
            }
            catch (Exception ex)
            {
                Log.LogWarning("IPC: Failed to accept action client: " + ex.Message);
                return false;
            }
        }

        /// <summary>
        /// Sends a length-prefixed message on the given stream.
        /// Returns false if the send failed (connection broken).
        /// </summary>
        private bool TrySend(NetworkStream stream, string json)
        {
            try
            {
                byte[] payload = Encoding.UTF8.GetBytes(json);
                byte[] lengthPrefix = IntToBigEndianBytes(payload.Length);

                stream.Write(lengthPrefix, 0, 4);
                stream.Write(payload, 0, payload.Length);
                stream.Flush();
                return true;
            }
            catch (Exception ex)
            {
                Log.LogWarning("IPC: Send failed: " + ex.Message);
                return false;
            }
        }

        /// <summary>
        /// Non-blocking receive of a length-prefixed message.
        /// Returns null if no data is available or read fails.
        /// Returns the JSON string if a complete message was read.
        /// </summary>
        private string TryReceive(NetworkStream stream)
        {
            try
            {
                if (stream == null || !stream.DataAvailable)
                    return null;

                // Read 4-byte length prefix
                byte[] lengthBytes = ReadExact(stream, 4);
                if (lengthBytes == null)
                    return null;

                int payloadLength = BigEndianBytesToInt(lengthBytes);
                if (payloadLength <= 0 || payloadLength > ReadBufferSize * 16)
                {
                    Log.LogWarning("IPC: Invalid payload length: " + payloadLength);
                    return null;
                }

                // Read the full payload
                byte[] payload = ReadExact(stream, payloadLength);
                if (payload == null)
                {
                    Log.LogWarning("IPC: Incomplete payload read");
                    return null;
                }

                return Encoding.UTF8.GetString(payload);
            }
            catch (Exception ex)
            {
                Log.LogWarning("IPC: Receive failed: " + ex.Message);
                DisconnectAction();
                return null;
            }
        }

        /// <summary>
        /// Reads exactly 'count' bytes from the stream, blocking until all bytes arrive.
        /// Returns null on failure.
        /// </summary>
        private byte[] ReadExact(NetworkStream stream, int count)
        {
            byte[] buffer = new byte[count];
            int offset = 0;
            while (offset < count)
            {
                int read = stream.Read(buffer, offset, count - offset);
                if (read <= 0)
                    return null;
                offset += read;
            }
            return buffer;
        }

        private void DisconnectState()
        {
            if (stateStream != null)
            {
                try { stateStream.Close(); } catch (Exception) { }
                stateStream = null;
            }
            if (stateClient != null)
            {
                try { stateClient.Close(); } catch (Exception) { }
                stateClient = null;
                Log.LogInfo("IPC: State client disconnected");
            }
        }

        private void DisconnectAction()
        {
            if (actionStream != null)
            {
                try { actionStream.Close(); } catch (Exception) { }
                actionStream = null;
            }
            if (actionClient != null)
            {
                try { actionClient.Close(); } catch (Exception) { }
                actionClient = null;
                Log.LogInfo("IPC: Action client disconnected");
            }
        }

        /// <summary>Converts an int to a 4-byte big-endian byte array.</summary>
        private static byte[] IntToBigEndianBytes(int value)
        {
            byte[] bytes = new byte[4];
            bytes[0] = (byte)((value >> 24) & 0xFF);
            bytes[1] = (byte)((value >> 16) & 0xFF);
            bytes[2] = (byte)((value >> 8) & 0xFF);
            bytes[3] = (byte)(value & 0xFF);
            return bytes;
        }

        /// <summary>Converts a 4-byte big-endian byte array to an int.</summary>
        private static int BigEndianBytesToInt(byte[] bytes)
        {
            return (bytes[0] << 24) | (bytes[1] << 16) | (bytes[2] << 8) | bytes[3];
        }
    }
}
