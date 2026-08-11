using System;

namespace DotEAgent.Ipc
{
    /// <summary>
    /// Manages raw TCP socket lifecycle and message routing.
    /// Uses length-prefixed framing: [4-byte big-endian length][UTF-8 JSON payload].
    /// Port 5555: state push (mod -> Python)
    /// Port 5556: action request/response (Python -> mod -> Python)
    /// </summary>
    public interface IIpcBridge : IDisposable
    {
        /// <summary>Starts TCP listeners on port 5555 (state) and port 5556 (actions).</summary>
        void Start();

        /// <summary>Sends a length-prefixed UTF-8 JSON string to the connected Python client on port 5555.</summary>
        void SendState(string jsonPayload);

        /// <summary>
        /// Non-blocking poll for an incoming action command on port 5556.
        /// Returns the raw JSON string if a message is available, or null if nothing to read.
        /// </summary>
        string PollAction();

        /// <summary>Sends a length-prefixed UTF-8 JSON response back to the Python agent on port 5556.</summary>
        void SendResponse(string jsonPayload);

        /// <summary>Whether a Python client is connected on the state port (5555).</summary>
        bool IsStateConnected { get; }

        /// <summary>Whether a Python client is connected on the action port (5556).</summary>
        bool IsActionConnected { get; }
    }
}
