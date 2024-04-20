import subprocess
import io

# TODO
# Modify FrontiersAnimDecompress to exchange byte data directly with Python

filepath = "C:/Users/adelj/Documents/Blender/FrontiersModding/Tests/BoneRelocTests/chr_sonic@climbing01_r.outanim"
cmd = "C:\\Users\\adelj\\AppData\\Roaming\\Blender Foundation\\Blender\\4.1\\scripts\\addons\\FrontiersAnimationTools\\FrontiersAnimDecompress\\FrontiersAnimDecompress.exe"
file = open(filepath, 'rb')
data = io.BytesIO()
data.write(file.read())


process = subprocess.Popen(cmd, stdin=subprocess.PIPE, creationflags=subprocess.CREATE_NO_WINDOW)
process.stdin.write(data.getvalue())
process.stdin.close()
process.wait()

# subprocess.run(cmd, shell=True, input=data.getvalue(), check=True)

'''
process = subprocess.Popen(cmd, stdout=subprocess.PIPE, creationflags=0x08000000)
process.wait()
'''