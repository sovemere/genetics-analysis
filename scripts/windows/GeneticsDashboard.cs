// Windows launcher for the local dashboard: starts `genetics serve` from this checkout and
// opens it in the default browser. Build it with build_launcher.ps1 beside this file; the
// .exe lands at the repository root and is gitignored (*.exe).
//
// It adds nothing to what `uv run genetics serve` does: the server binds loopback only,
// logs no request URLs, and stops when this window is closed or Ctrl+C is pressed.
// With --verify it first runs `genetics runs list --verify`, so the deep checks a saved run
// repeats after a source change happen here, with progress shown, rather than on the first
// dashboard page. build_launcher.ps1 also makes a shortcut that passes it.
// Written for the C# 5 compiler that ships with Windows (.NET Framework 4).

using System;
using System.Diagnostics;
using System.IO;
using System.Net;
using System.Net.Sockets;
using System.Text;
using System.Text.RegularExpressions;

internal static class GeneticsDashboard
{
    private const int PreferredPort = 8765;

    private static int Main(string[] args)
    {
        Console.Title = "Genetics dashboard";
        bool openBrowser = Array.IndexOf(args, "--no-browser") < 0;
        bool verifyFirst = Array.IndexOf(args, "--verify") >= 0;

        string root = FindRepositoryRoot(AppDomain.CurrentDomain.BaseDirectory);
        if (root == null)
        {
            return Fail(
                "Cannot find the genetics-analysis checkout above "
                    + AppDomain.CurrentDomain.BaseDirectory
                    + ". Keep this .exe inside the repository."
            );
        }

        // Ctrl+C reaches the child through the shared console; wait for it to finish.
        Console.CancelKeyPress += delegate(object sender, ConsoleCancelEventArgs e)
        {
            e.Cancel = true;
        };

        if (verifyFirst)
        {
            ProcessStartInfo check = GeneticsCommand(root, "runs list --verify");
            if (check == null)
            {
                return MissingRunner(root);
            }
            Console.WriteLine("Checking every saved run before starting the dashboard.");
            Console.WriteLine(
                "This repeats each run's deep checks: about an hour for an imputed run."
            );
            Console.WriteLine("Press Ctrl+C to stop; the dashboard will not start.");
            Console.WriteLine();
            // Output is not redirected, so the listing and its progress lines appear here.
            using (Process verify = Process.Start(check))
            {
                verify.WaitForExit();
                if (verify.ExitCode != 0)
                {
                    return Fail(
                        "Checking the saved runs stopped (exit code "
                            + verify.ExitCode
                            + "). The dashboard was not started."
                    );
                }
            }
            Console.WriteLine();
        }

        // A fixed port keeps bookmarked run URLs working; if it is taken, let the OS choose.
        string port = PortIsFree(PreferredPort) ? PreferredPort.ToString() : "0";
        ProcessStartInfo info = GeneticsCommand(root, "serve --port " + port + " --json");
        if (info == null)
        {
            return MissingRunner(root);
        }
        info.RedirectStandardOutput = true;
        info.StandardOutputEncoding = Encoding.UTF8;

        Console.WriteLine("Starting the dashboard from " + root);
        Console.WriteLine("Close this window or press Ctrl+C to stop it.");
        Console.WriteLine();

        using (Process server = Process.Start(info))
        {
            string url = ReadUrl(server.StandardOutput);
            if (url == null)
            {
                server.WaitForExit();
                return Fail("The dashboard did not start (exit code " + server.ExitCode + ").");
            }
            Console.WriteLine("Dashboard: " + url);
            if (verifyFirst)
            {
                Console.WriteLine(
                    "Saved runs were checked above; a run that failed is listed with its status."
                );
            }
            else
            {
                Console.WriteLine(
                    "The first page opens the most recent run. After the source has changed, its"
                );
                Console.WriteLine(
                    "first read repeats the run's deep checks (about 54 min for an imputed run)."
                );
                Console.WriteLine(
                    "Start the launcher with --verify (or its \"verify first\" shortcut) to pay"
                );
                Console.WriteLine("that up front, with progress shown.");
            }
            if (openBrowser)
            {
                Process.Start(new ProcessStartInfo(url) { UseShellExecute = true });
            }

            string line;
            while ((line = server.StandardOutput.ReadLine()) != null)
            {
                Console.WriteLine(line);
            }
            server.WaitForExit();
            if (server.ExitCode != 0)
            {
                return Fail("The dashboard stopped with exit code " + server.ExitCode + ".");
            }
        }
        return 0;
    }

    /// <summary>The checkout holding this .exe: the nearest parent with the package source.</summary>
    private static string FindRepositoryRoot(string start)
    {
        DirectoryInfo directory = new DirectoryInfo(start.TrimEnd('\\', '/'));
        while (directory != null)
        {
            if (
                File.Exists(Path.Combine(directory.FullName, "pyproject.toml"))
                && Directory.Exists(Path.Combine(directory.FullName, @"src\genetics"))
            )
            {
                return directory.FullName;
            }
            directory = directory.Parent;
        }
        return null;
    }

    /// <summary>`uv run genetics ...` when uv is on PATH, else the checkout's own venv.</summary>
    private static ProcessStartInfo GeneticsCommand(string root, string arguments)
    {
        string uv = FindOnPath("uv.exe");
        string venv = Path.Combine(root, @".venv\Scripts\genetics.exe");
        ProcessStartInfo info;
        if (uv != null)
        {
            info = new ProcessStartInfo(uv, "run genetics " + arguments);
        }
        else if (File.Exists(venv))
        {
            info = new ProcessStartInfo(venv, arguments);
        }
        else
        {
            return null;
        }
        info.WorkingDirectory = root;
        info.UseShellExecute = false;
        info.EnvironmentVariables["PYTHONUTF8"] = "1";
        return info;
    }

    private static int MissingRunner(string root)
    {
        return Fail(
            "Neither uv nor "
                + Path.Combine(root, @".venv\Scripts\genetics.exe")
                + " was found. Install uv, or run `uv sync` in the repository."
        );
    }

    private static string FindOnPath(string name)
    {
        string path = Environment.GetEnvironmentVariable("PATH") ?? "";
        foreach (string entry in path.Split(Path.PathSeparator))
        {
            try
            {
                string candidate = Path.Combine(entry.Trim().Trim('"'), name);
                if (File.Exists(candidate))
                {
                    return candidate;
                }
            }
            catch (ArgumentException)
            {
                // A malformed PATH entry; skip it.
            }
        }
        return null;
    }

    private static bool PortIsFree(int port)
    {
        TcpListener probe = new TcpListener(IPAddress.Loopback, port);
        try
        {
            probe.Start();
            return true;
        }
        catch (SocketException)
        {
            return false;
        }
        finally
        {
            probe.Stop();
        }
    }

    /// <summary>The loopback URL from `serve --json`, read up to its closing brace.</summary>
    private static string ReadUrl(StreamReader output)
    {
        StringBuilder text = new StringBuilder();
        string line;
        while ((line = output.ReadLine()) != null)
        {
            text.AppendLine(line);
            if (line == "}")
            {
                break;
            }
        }
        Match url = Regex.Match(
            text.ToString(),
            "\"url\"\\s*:\\s*\"(http://(?:127\\.0\\.0\\.1|localhost|\\[::1\\]):\\d+)\""
        );
        if (!url.Success || !Regex.IsMatch(text.ToString(), "\"ok\"\\s*:\\s*true"))
        {
            Console.Write(text.ToString());
            return null;
        }
        return url.Groups[1].Value;
    }

    private static int Fail(string message)
    {
        Console.WriteLine();
        Console.WriteLine(message);
        Console.WriteLine("Press Enter to close.");
        Console.ReadLine();
        return 1;
    }
}
