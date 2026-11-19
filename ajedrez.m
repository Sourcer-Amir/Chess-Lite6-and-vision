function r = ajedrez(cmd, varargin)
% AJEDREZ  Llama al sistema de ajedrez que corre en la Raspberry Pi (servidor.py).
%   r = ajedrez('estado')
%   r = ajedrez('leer_tablero')
%   r = ajedrez('iniciar', 'blancas_mueven', true, 'enroques', 'auto')
%   r = ajedrez('iniciar_fen', 'fen', '8/8/8/8/8/8/8/8 w - - 0 1')
%   r = ajedrez('jugada_humano')
%   r = ajedrez('confirmar_jugada', 'uci', 'e7e8q')
%   r = ajedrez('jugada_robot')                 % la decide Stockfish
%   r = ajedrez('jugada_robot', 'uci', 'e2e4')  % jugada indicada
%   r = ajedrez('home')
%   ajedrez('cerrar')
% Requiere MATLAB R2020b o posterior (tcpclient con writeline/readline).

IP = "192.168.1.50";   % <-- IP de la Raspberry Pi
PUERTO = 5005;

persistent t
if strcmp(cmd, 'cerrar')
    clear t; r = struct('ok', true); return
end
if isempty(t)
    t = tcpclient(IP, PUERTO, 'Timeout', 180);   % los movimientos del robot tardan
    configureTerminator(t, "LF");
end

args = struct();
for k = 1:2:numel(varargin)
    args.(varargin{k}) = varargin{k+1};
end
msg = struct('cmd', cmd, 'args', args);

writeline(t, jsonencode(msg));
r = jsondecode(readline(t));
if isfield(r, 'ok') && ~r.ok
    warning('ajedrez:error', '%s', jsonencode(r));
end
end
